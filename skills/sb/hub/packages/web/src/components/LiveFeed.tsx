/**
 * Live: what a running worker is doing, read from its log as it writes it, and a box to steer it.
 * Its sentences read as text, each tool call is one line that opens on its result, a failure is red. A message goes
 * to the worker at its next step (the hub's hook hands it over); its line says when it was read.
 */
import { IconSend } from "@tabler/icons-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type * as React from "react";
import type { Message } from "@sb-hub/contract";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { headlineOf, rowsOf, useFeed, type FeedRow } from "@/lib/feed.ts";
import { say } from "@/lib/notice.ts";
import { cn } from "@/lib/utils";
import { useBoard } from "./context.tsx";

const clock = (sec: number): string => new Date(sec * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

/** The one-tap steers: each is a plain message, so the worker reads it like any other. */
export function quickSteers(paths: readonly string[]): readonly (readonly [string, string])[] {
  const steers: [string, string][] = [
    ["Where are you?", "In one or two sentences: what you are doing now, what is left, and anything in your way. Then go on."],
    ["Wrap up now", "Wrap up now: finish the step you are on, commit what works, write your report, and end."],
  ];
  if (paths.length > 0) steers.push(["Stay in its files", `Stay inside the ticket's files: ${paths.join(", ")}. Undo any change outside them, or say in one sentence why the ticket needs it.`]);
  return steers;
}

function Row({ r }: { r: FeedRow }): React.JSX.Element {
  if (r.k === "say") return <li className="px-3 py-1.5 whitespace-pre-wrap">{r.text}</li>;
  if (r.k === "owner") return <li className="bg-brand/10 px-3 py-1.5 whitespace-pre-wrap"><span className="font-medium">You: </span>{r.text}</li>;
  if (r.k === "line") return <li className="px-3 py-1 font-mono text-xs break-all text-muted-foreground">{r.text}</li>;
  if (r.k === "start") return <li className="px-3 py-1 text-xs text-muted-foreground">{`Started${r.model ? ` on ${r.model}` : ""}`}</li>;
  if (r.k === "end") return <li className={cn("px-3 py-1.5 whitespace-pre-wrap", !r.ok && "text-destructive")}><span className="font-medium">{r.ok ? "Ended: " : "Ended with an error: "}</span>{r.text}</li>;
  const state = r.result === null ? "running" : r.result.ok ? "done" : "failed";
  return (
    <li className="px-3 py-1">
      <details className="group">
        <summary className={cn("flex cursor-pointer list-none items-center gap-2 text-xs", state === "failed" ? "text-destructive" : "text-muted-foreground")}>
          <span role="img" aria-label={state} className={cn("size-1.5 shrink-0 rounded-full", state === "failed" ? "bg-destructive" : state === "running" ? "bg-brand motion-safe:animate-pulse" : "bg-muted-foreground/40")} />
          <span className="shrink-0 font-medium">{r.name}</span>
          <span className="min-w-0 flex-1 truncate font-mono">{r.arg}</span>
        </summary>
        {r.result !== null && r.result.text !== "" && <pre className="mt-1 max-h-48 overflow-auto rounded bg-muted p-2 text-xs whitespace-pre-wrap break-all">{r.result.text}</pre>}
      </details>
    </li>
  );
}

function messageState(m: Message): string {
  if (m.delivered !== null) return `read at ${clock(m.delivered)}`;
  if (m.lost !== undefined) return "not delivered: the worker ended first";
  return "waits for its next step";
}

export function LiveFeed({ itemKey, paths, running }: { itemKey: string; paths: readonly string[]; running: boolean }): React.JSX.Element {
  const { state, writes, down } = useBoard();
  const feed = useFeed(itemKey, true);
  const rows = rowsOf(feed.events);
  const headline = headlineOf(feed.events);
  const box = useRef<HTMLOListElement>(null);
  const pinned = useRef(true);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const mine = Object.entries(state.messages)
    .filter(([, m]) => m.to === itemKey)
    .sort(([, a], [, b]) => a.at - b.at)
    .slice(-3);
  // the list follows the newest line until you scroll up to read; scrolling back down follows again
  useLayoutEffect(() => {
    const el = box.current;
    if (el !== null && pinned.current) el.scrollTop = el.scrollHeight;
  }, [rows.length]);
  useEffect(() => {
    pinned.current = true;
  }, [itemKey]);
  const send = async (words: string): Promise<void> => {
    if (!words.trim()) return;
    setSending(true);
    const out = await writes.send(itemKey, words.trim());
    setSending(false);
    say(out.ok ? { ok: true, words: "Sent: it reads it at its next step." } : out);
    if (out.ok && words === text) setText("");
  };
  const off = down || sending || !running;
  return (
    <section className="flex flex-col gap-2" aria-label="Live">
      <h3 className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        Live
        {feed.live && <span role="img" aria-label="live" className="size-1.5 rounded-full bg-brand motion-safe:animate-pulse" />}
      </h3>
      {headline !== null && (
        <p className="text-sm">
          <span className="text-muted-foreground">Now: </span>
          {headline}
        </p>
      )}
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{feed.failed ? "The hub did not answer for its log." : feed.log === null ? "No log yet: it is starting." : "Nothing yet."}</p>
      ) : (
        <ol
          ref={box}
          role="log"
          aria-label="Live feed"
          onScroll={(ev) => {
            const el = ev.currentTarget;
            pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
          }}
          className="flex max-h-96 flex-col divide-y overflow-y-auto rounded-lg border text-sm"
        >
          {feed.cut && <li className="px-3 py-1 text-xs text-muted-foreground">Earlier lines are in the log.</li>}
          {rows.map((r, n) => (
            <Row key={n} r={r} />
          ))}
        </ol>
      )}
      {running && (
        <form
          className="flex flex-col gap-2"
          aria-label="Steer the worker"
          onSubmit={(ev) => {
            ev.preventDefault();
            void send(text);
          }}
        >
          <Textarea
            aria-label="Message to the worker"
            placeholder="Tell the worker something; it reads it at its next step"
            value={text}
            onChange={(ev) => {
              setText(ev.target.value);
            }}
            onKeyDown={(ev) => {
              if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
                ev.preventDefault();
                void send(text);
              }
            }}
          />
          <div className="flex flex-wrap items-center gap-1.5">
            <Button type="submit" size="xs" variant="brand" disabled={off || !text.trim()}>
              <IconSend aria-hidden />
              Send
            </Button>
            {quickSteers(paths).map(([label, words]) => (
              <Button key={label} type="button" size="xs" variant="outline" disabled={off} title={words} onClick={() => void send(words)}>
                {label}
              </Button>
            ))}
          </div>
        </form>
      )}
      {mine.length > 0 && (
        <ul aria-label="Your messages to it" className="flex flex-col gap-1 text-xs">
          {mine.map(([id, m]) => (
            <li key={id} className="flex items-baseline gap-2">
              <span className="min-w-0 flex-1 truncate" title={m.text}>{m.text}</span>
              <span className={cn("shrink-0", m.delivered !== null ? "text-ok" : m.lost !== undefined ? "text-destructive" : "text-muted-foreground")}>{messageState(m)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
