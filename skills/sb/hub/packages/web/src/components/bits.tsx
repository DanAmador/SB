/** Small pieces the views share: state icons, section headings, empty lines, checks and pictures. */
import {
  IconBan,
  IconBell,
  IconChevronRight,
  IconCircleCheck,
  IconHelpCircle,
  IconLayoutSidebarRight,
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
import type { CheckRun, Links, QueueItem } from "@sb-hub/contract";
import { mediaUrl } from "@/lib/api.ts";
import { plural } from "@/lib/board.ts";
import { setLink } from "@/lib/link.ts";
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

/** A check exits 75 (EX_TEMPFAIL) when the tool it needs did not answer: it could not run, it did not fail. */
const EX_TEMPFAIL = 75;

export function Checks({ checks }: { checks: readonly CheckRun[] }): React.JSX.Element | null {
  if (checks.length === 0) return null;
  const notRun = checks.filter((c) => c.code === EX_TEMPFAIL).length;
  const bad = checks.filter((c) => c.code !== 0 && c.code !== EX_TEMPFAIL).length;
  return (
    <Fold
      summary={
        bad > 0 ? (
          <span className="font-medium text-destructive">{`${String(bad)} of ${plural(checks.length, "check")} failed`}</span>
        ) : notRun > 0 ? (
          <span className="font-medium text-warn">{`${String(notRun)} of ${plural(checks.length, "check")} could not run`}</span>
        ) : (
          <span className="text-ok">{`${plural(checks.length, "check")} passed`}</span>
        )
      }
    >
      <ul className="mt-1 flex flex-col gap-2 pl-5">
        {checks.map((c, n) => (
          <li key={`${c.cmd}-${String(n)}`} className="flex flex-col gap-1 text-xs">
            <div className="flex flex-wrap items-center gap-1.5">
              {c.code === 0 ? <ToneIcon icon={IconCircleCheck} tone="ok" label="passed" /> : c.code === EX_TEMPFAIL ? <ToneIcon icon={IconBan} tone="warn" label="could not run" /> : <ToneIcon icon={IconX} tone="bad" label="failed" />}
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

/**
 * A ticket's title: it opens the ticket in Obsidian (the hub renders no ticket text), and a small button beside it opens the
 * panel (digest and actions). With no note to open, the title opens the panel itself. `stretch` makes the whole row the link.
 */
export function TicketTitle({ itemKey, links, className, stretch, children }: { itemKey: string; links: Links | undefined; className?: string; stretch?: boolean; children: React.ReactNode }): React.JSX.Element {
  const href = links?.ticket ?? null;
  const open = (): void => {
    setLink({ t: itemKey });
  };
  const cls = cn("min-w-0 text-left text-sm font-medium hover:underline focus-visible:underline focus-visible:outline-none", stretch === true && "after:absolute after:inset-0 after:content-['']", className);
  return (
    <>
      {href === null ? (
        <button type="button" onClick={open} className={cls}>
          {children}
        </button>
      ) : (
        <a href={href} title="Open in Obsidian" className={cls}>
          {children}
        </a>
      )}
      {href !== null && (
        <button
          type="button"
          aria-label="Show details"
          title="Show details and actions"
          onClick={open}
          className="relative z-10 -my-1 inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <IconLayoutSidebarRight className="size-4" aria-hidden />
        </button>
      )}
    </>
  );
}

/** A map's name, opening its map note in Obsidian when it has one. */
export function MapName({ links, name, title }: { links: Links | undefined; name: string; title?: string }): React.JSX.Element {
  const href = links?.map ?? null;
  if (href === null) return <span title={title}>{name}</span>;
  return (
    <a href={href} title={title === undefined ? "Open the map in Obsidian" : `${title} · open the map in Obsidian`} className="relative z-10 underline-offset-2 hover:underline">
      {name}
    </a>
  );
}

/** The worker's report and log, which open in Obsidian: a link is there only when the note is. */
export function FileLinks({ item }: { item: QueueItem }): React.JSX.Element | null {
  const found: [string, string | null][] = [["Report", item.links.report], ["Review", item.links.review ?? null], ["Log", item.links.log]];
  const shown = found.filter((x): x is [string, string] => x[1] !== null);
  if (shown.length === 0) return null;
  return (
    <div className="relative z-10 flex flex-wrap gap-3 text-xs">
      {shown.map(([word, href]) => (
        <a key={word} className="inline-flex items-center gap-1 text-brand underline-offset-2 hover:underline" href={href} title={`Open the ${word.toLowerCase()} in Obsidian`}>
          <IconNotebook className="size-3.5" aria-hidden />
          {word}
        </a>
      ))}
    </div>
  );
}
