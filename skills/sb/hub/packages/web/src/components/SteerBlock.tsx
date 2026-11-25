/**
 * Steer: the three words of a ticket that fix a worker which drifted. Done when, its files and what it comes after,
 * each with Edit, a field, and Save with a confirmation. The hub writes them through sbmap and leaves a dated comment
 * with the old value; a loop in the order or an unknown ticket comes back as sbmap's own words. While its worker runs,
 * Done when and Files still change, and the hub sends the worker the new value (ticket 197; the message shows under
 * the Live block's "Your messages to it"); what it comes after waits until it stops. All three wait while its Opus
 * review runs. Title and why stay in Obsidian.
 */
import { IconPencil } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import type { TicketAction, TicketRow } from "@sb-hub/contract";
import { Button } from "@/components/ui/button";
import { Label, Textarea } from "@/components/ui/input";
import { say } from "@/lib/notice.ts";
import { useBoard } from "./context.tsx";

type Field = "done_when" | "paths" | "after";
const NAMES: Readonly<Record<Field, string>> = { done_when: "Done when", paths: "Files", after: "Comes after" };
const SAVED: Readonly<Record<Field, string>> = { done_when: "Done when changed.", paths: "Files changed.", after: "Order changed." };
const num = (b: number | string): string => String(b);

/** The fields its running worker can be told about; the order is not one of them. */
const LIVE: ReadonlySet<Field> = new Set<Field>(["done_when", "paths"]);

export function SteerBlock({ t, running }: { t: TicketRow; running: boolean }): React.JSX.Element {
  const { ix, writes, down, state } = useBoard();
  const key = `${t.map}#${String(t.num)}`;
  // `running` is on while its worker or its review runs; only a worker can be told
  const worker = running && state.queue.items.some((i) => i.key === key && i.state === "running");
  const locked = (f: Field): boolean => running && !(worker && LIVE.has(f));
  const [field, setField] = useState<Field | null>(null);
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<readonly string[]>([]);
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const sameMap = [...ix.byKey.values()].filter((o) => o.map === t.map && o.num !== t.num).sort((a, b) => a.num - b.num);
  const listed = new Set(sameMap.map((o) => String(o.num)));
  const kept = t.blocked_by.map(num).filter((b) => !listed.has(b)); // a finished ticket or another map's: kept as it is
  const titleOf = (n: string): string => ix.byKey.get(`${t.map}#${n}`)?.title ?? `ticket ${n}`;
  const current: Readonly<Record<Field, string>> = {
    done_when: t.done_when.trim(),
    paths: t.paths.join("\n"),
    after: t.blocked_by.map((b) => titleOf(num(b))).join("; "),
  };
  const open = (f: Field): void => {
    setField(f);
    setConfirm(false);
    setErr(null);
    setText(f === "done_when" ? t.done_when : t.paths.join("\n"));
    setPicked(t.blocked_by.map(num).filter((b) => listed.has(b)));
  };
  const value = (f: Field): string => (f === "after" ? [...kept, ...picked].join(",") : text);
  // the form closes at once and the page draws the change; a refusal opens it again, with what was typed and why
  const save = async (): Promise<void> => {
    if (field === null) return;
    const f = field;
    setConfirm(false);
    setField(null);
    const out = await writes.ticket(f satisfies TicketAction, { key, text: value(f) }, worker ? `${SAVED[f]} The worker is told.` : SAVED[f]);
    say(out);
    if (!out.ok) {
      setField(f);
      setErr(out.words);
    }
  };
  return (
    <section className="flex flex-col gap-1.5" aria-label="Steer">
      <h3 className="text-xs font-medium text-muted-foreground">Steer</h3>
      {running && (
        <p className="text-sm text-warn">
          {worker
            ? "Its worker is running: a change to Done when or Files is saved and sent to it. The order waits until it stops."
            : "Its review is running, so these cannot change now."}
        </p>
      )}
      <ul className="flex flex-col gap-2">
        {(["done_when", "paths", "after"] as const).map((f) => (
          <li key={f} className="flex flex-col gap-1 rounded-lg border bg-card p-2.5" data-field={f}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium">{NAMES[f]}</span>
              <Button size="xs" variant="outline" disabled={locked(f) || down} aria-label={`Edit ${NAMES[f]}`} onClick={() => { open(f); }}>
                <IconPencil aria-hidden />
                {locked(f) ? (worker ? "Stop it first" : "Wait for the review") : "Edit"}
              </Button>
            </div>
            <p className="line-clamp-3 whitespace-pre-line break-words text-sm text-muted-foreground" data-testid={`steer-${f}`}>
              {current[f] || "none"}
            </p>
            {field === f && !locked(f) && (
              <form
                className="mt-1 flex flex-col gap-2"
                onSubmit={(ev) => {
                  ev.preventDefault();
                  if (f === "done_when" && !text.trim()) {
                    setErr("Type it first.");
                    return;
                  }
                  setErr(null);
                  setConfirm(true);
                }}
              >
                {f === "after" ? (
                  <fieldset className="flex flex-col gap-1">
                    <legend className="text-xs font-medium text-muted-foreground">Tickets of this map it waits for</legend>
                    {sameMap.length === 0 && <p className="text-sm text-muted-foreground">No other open ticket in this map.</p>}
                    {sameMap.map((o) => (
                      <label key={o.num} className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={picked.includes(String(o.num))}
                          onChange={(ev) => { setPicked(ev.currentTarget.checked ? [...picked, String(o.num)] : picked.filter((p) => p !== String(o.num))); }}
                        />
                        <span className="min-w-0 break-words">{o.title}</span>
                      </label>
                    ))}
                  </fieldset>
                ) : (
                  <Label>
                    {f === "done_when" ? "What has to be true when it is done" : "One file or folder per line, empty for none"}
                    <Textarea value={text} maxLength={4000} onChange={(ev) => { setText(ev.currentTarget.value); setConfirm(false); }} />
                  </Label>
                )}
                {err !== null && <p role="alert" className="text-sm text-destructive">{err}</p>}
                {confirm ? (
                  <div role="alert" className="flex flex-col gap-2 rounded-md bg-warn-soft p-2.5 text-sm">
                    <span>Change {NAMES[f]}? The old value stays as a comment on the ticket.{worker ? " Its worker gets the new one as a message." : ""}</span>
                    <div className="flex gap-2">
                      <Button type="button" size="xs" disabled={down} autoFocus onClick={() => void save()}>
                        Yes, save it
                      </Button>
                      <Button type="button" size="xs" variant="ghost" onClick={() => { setConfirm(false); }}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="flex gap-2">
                    <Button type="submit" size="xs" disabled={down}>Save…</Button>
                    <Button type="button" size="xs" variant="ghost" onClick={() => { setField(null); }}>Cancel</Button>
                  </div>
                )}
              </form>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
