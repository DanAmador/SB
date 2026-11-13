/** Small pieces the views share: state icons, section headings, empty lines, checks and pictures. */
import {
  IconBan,
  IconBell,
  IconChevronRight,
  IconCircleCheck,
  IconHelpCircle,
  IconLoader2,
  IconMessage,
  IconNotebook,
  IconPlayerPause,
  IconPlayerPlay,
  IconX,
  IconZzz,
  type Icon,
} from "@tabler/icons-react";
import type * as React from "react";
import type { CheckRun, QueueItem } from "@sb-hub/contract";
import { itemUrl, mediaUrl } from "@/lib/api.ts";
import { plural, runFiles, vaultUri } from "@/lib/board.ts";
import { useSelfChecks } from "@/lib/hub.ts";
import { cn } from "@/lib/utils";

type Tone = "brand" | "ok" | "warn" | "bad" | "muted";
const TONE: Readonly<Record<Tone, string>> = {
  brand: "text-brand",
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-destructive",
  muted: "text-muted-foreground",
};

/** An agent's state: icon, word and tone. A needs-you bell and a your-turn bubble never read as the same thing. */
const AGENT: Readonly<Record<string, [Icon, string, Tone]>> = {
  working: [IconLoader2, "working", "brand"],
  done: [IconCircleCheck, "done", "ok"],
  blocked: [IconBan, "blocked", "bad"],
  "needs you": [IconBell, "needs you", "bad"],
  "your turn": [IconMessage, "your turn", "brand"],
  waiting: [IconPlayerPause, "waiting", "muted"],
  idle: [IconZzz, "idle", "muted"],
};

export function StateIcon({ state, className }: { state: string | undefined; className?: string }): React.JSX.Element {
  const [Ic, word, tone] = AGENT[state ?? ""] ?? [IconHelpCircle, state ?? "unknown", "muted"];
  return (
    <span role="img" aria-label={word} title={word} className={cn("inline-flex shrink-0", TONE[tone], className)}>
      <Ic className={cn("size-4", state === "working" && "animate-spin [animation-duration:1.6s]")} aria-hidden />
    </span>
  );
}

export function ToneIcon({ icon: Ic, tone, label, spin }: { icon: Icon; tone: Tone; label: string; spin?: boolean }): React.JSX.Element {
  return (
    <span role="img" aria-label={label} title={label} className={cn("inline-flex shrink-0", TONE[tone])}>
      <Ic className={cn("size-4", spin === true && "animate-spin [animation-duration:1.6s]")} aria-hidden />
    </span>
  );
}

export const RunIcon = ({ paused }: { paused: boolean }): React.JSX.Element =>
  paused ? <IconPlayerPlay aria-hidden /> : <IconPlayerPause aria-hidden />;

export function SectionTitle({ children, aside, className }: { children: React.ReactNode; aside?: React.ReactNode; className?: string }): React.JSX.Element {
  return (
    <div className={cn("flex min-h-8 items-center gap-2", className)}>
      <h2 className="text-sm font-semibold">{children}</h2>
      {aside !== undefined && <div className="ml-auto flex items-center gap-1">{aside}</div>}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }): React.JSX.Element {
  return <p className="py-3 text-sm text-muted-foreground">{children}</p>;
}

/** A folding group: native details, so it works with the keyboard and keeps its state across polls. */
export function Fold({
  summary,
  children,
  defaultOpen,
  className,
}: {
  summary: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
  className?: string;
}): React.JSX.Element {
  return (
    <details className={cn("group/fold", className)} open={defaultOpen === true}>
      <summary className="flex min-h-8 items-center gap-1.5 rounded-md text-sm select-none hover:text-foreground">
        <IconChevronRight className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open/fold:rotate-90" aria-hidden />
        {summary}
      </summary>
      {children}
    </details>
  );
}

export function Checks({ checks }: { checks: readonly CheckRun[] }): React.JSX.Element | null {
  if (checks.length === 0) return null;
  const bad = checks.filter((c) => c.code !== 0).length;
  return (
    <Fold
      summary={
        bad > 0 ? (
          <span className="font-medium text-destructive">{`${String(bad)} of ${plural(checks.length, "check")} failed`}</span>
        ) : (
          <span className="text-ok">{`${plural(checks.length, "check")} passed`}</span>
        )
      }
    >
      <ul className="mt-1 flex flex-col gap-2 pl-5">
        {checks.map((c, n) => (
          <li key={`${c.cmd}-${String(n)}`} className="flex flex-col gap-1 text-xs">
            <div className="flex flex-wrap items-center gap-1.5">
              {c.code === 0 ? <ToneIcon icon={IconCircleCheck} tone="ok" label="passed" /> : <ToneIcon icon={IconX} tone="bad" label="failed" />}
              <code className="font-mono break-all">{c.cmd}</code>
              <span className="text-muted-foreground">
                {c.code === null ? "timed out" : `exit ${String(c.code)}`} · {String(Math.round(c.secs))} s
              </span>
            </div>
            {c.tail && <pre className="max-h-48 overflow-auto rounded-md bg-muted p-2 font-mono text-[11px] whitespace-pre-wrap text-muted-foreground">{c.tail}</pre>}
          </li>
        ))}
      </ul>
    </Fold>
  );
}

/** The worker's own self-checks, read from its report when opened. */
export function SelfChecks({ item }: { item: QueueItem }): React.JSX.Element | null {
  if (item.kind !== "ticket" || item.run === undefined) return null;
  return (
    <Fold summary={<span className="text-xs text-muted-foreground">Self-checks</span>}>
      <SelfChecksBody itemKey={item.key} />
    </Fold>
  );
}
function SelfChecksBody({ itemKey }: { itemKey: string }): React.JSX.Element {
  const q = useSelfChecks(itemKey, true);
  if (q.isPending) return <p className="pl-5 text-xs text-muted-foreground">Reading the report…</p>;
  if (q.isError) return <p className="pl-5 text-xs text-muted-foreground">No report to read yet.</p>;
  return <pre className="mt-1 ml-5 max-h-60 overflow-auto rounded-md bg-muted p-2 font-mono text-[11px] whitespace-pre-wrap">{q.data}</pre>;
}

const MEDIA = /\.(png|jpe?g|gif|webp|mp4|webm)$/i;
const isClip = (n: string): boolean => /\.(mp4|webm)$/i.test(n);

/** A worker's pictures and clips: three thumbnails in a row, or every one full width. */
export function Pictures({ item, full }: { item: QueueItem; full?: boolean }): React.JSX.Element | null {
  const ms = (item.media ?? []).filter((n) => MEDIA.test(n));
  if (ms.length === 0) return null;
  if (full === true) {
    return (
      <div className="flex flex-col gap-3">
        {ms.map((n) => (
          <figure key={n} className="min-w-0">
            {isClip(n) ? (
              <video src={`${mediaUrl(item.key, n)}#t=0.1`} controls preload="metadata" playsInline aria-label={n} className="w-full rounded-md border bg-muted" />
            ) : (
              <a href={mediaUrl(item.key, n)} target="_blank" rel="noopener noreferrer">
                <img loading="lazy" src={mediaUrl(item.key, n)} alt={n} className="max-h-[60vh] w-full rounded-md border bg-muted object-contain" />
              </a>
            )}
            <figcaption className="mt-1 text-xs break-all text-muted-foreground">{n}</figcaption>
          </figure>
        ))}
      </div>
    );
  }
  const more = ms.length - 3;
  return (
    <div className="grid max-w-72 grid-cols-3 gap-1.5">
      {ms.slice(0, 3).map((n) => (
        <a key={n} href={mediaUrl(item.key, n)} target="_blank" rel="noopener noreferrer" title={n} className="relative block aspect-[3/2] overflow-hidden rounded-md border bg-muted">
          {isClip(n) ? (
            <video src={`${mediaUrl(item.key, n)}#t=0.1`} preload="metadata" muted playsInline aria-label={n} className="size-full object-cover" />
          ) : (
            <img loading="lazy" src={mediaUrl(item.key, n)} alt={n} className="size-full object-cover" />
          )}
        </a>
      ))}
      {more > 0 && <span className="col-span-3 text-xs text-muted-foreground">{plural(more, "more picture")}</span>}
    </div>
  );
}

/** A notebook icon that opens a vault file in Obsidian, beside a row whose own click opens the panel. */
export function VaultLink({ path, what, className }: { path: string | null | undefined; what: string; className?: string }): React.JSX.Element | null {
  const href = vaultUri(path);
  if (href === null) return null;
  return (
    <a
      href={href}
      aria-label={`Open ${what} in Obsidian`}
      title={`Open ${what} in Obsidian`}
      className={cn(
        "inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        className,
      )}
      onClick={(ev) => {
        ev.stopPropagation();
      }}
    >
      <IconNotebook className="size-4" aria-hidden />
    </a>
  );
}

/** The worker's report and log: in Obsidian when they are vault files, else as the hub serves them. */
export function FileLinks({ item }: { item: QueueItem }): React.JSX.Element | null {
  const f = runFiles(item);
  const links: [string, string][] = [];
  if (f.report !== null) links.push(["Report", vaultUri(f.report) ?? itemUrl("report", item.key)]);
  if (f.log !== null) links.push(["Log", vaultUri(f.log) ?? itemUrl("log", item.key)]);
  if (links.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-3 text-xs">
      {links.map(([word, href]) => (
        <a key={word} className="inline-flex items-center gap-1 text-brand underline-offset-2 hover:underline" href={href} {...(href.startsWith("obsidian:") ? {} : { target: "_blank", rel: "noopener noreferrer" })}>
          {href.startsWith("obsidian:") && <IconNotebook className="size-3.5" aria-hidden />}
          {word}
        </a>
      ))}
    </div>
  );
}
