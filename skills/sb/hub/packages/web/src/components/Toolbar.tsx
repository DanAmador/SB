/** The one toolbar: pause, the run's accounts and when the run should finish, then the command menu and the theme. */
import { IconCommand, IconMoon, IconRobot, IconSearch, IconSettings, IconSun, IconClock } from "@tabler/icons-react";
import type * as React from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { accountState, endsAt, hm, mapEtas, mapTitle, plural, poolOf, usageOf } from "@/lib/board.ts";
import { say } from "@/lib/notice.ts";
import { setGraphLayout, useGraphLayout, type GraphLayout } from "@/lib/layout.ts";
import { setTheme, useTheme } from "@/lib/theme.ts";
import { cn } from "@/lib/utils";
import { RunIcon } from "./bits.tsx";
import { Pace } from "./Pace.tsx";
import { useBoard } from "./context.tsx";

export function Toolbar({ onCommand, view }: { onCommand: () => void; view: string }): React.JSX.Element {
  const { state, queueWrite, down, busy } = useBoard();
  const q = state.queue;
  const off = down || busy;
  return (
    <div className="flex items-center gap-1.5">
      <Button
        size="sm"
        variant={q.paused ? "brand" : "outline"}
        disabled={off}
        onClick={() => {
          void queueWrite("POST /api/queue/pause", { paused: !q.paused }, q.paused ? "Resumed: the queue runs." : "Paused: nothing new starts.");
        }}
      >
        <RunIcon paused={q.paused} />
        {q.paused ? "Resume" : "Pause"}
      </Button>
      {view === "run" && <Accounts />}
      <Pace />
      <EtaChip />
      <Button variant="outline" size="sm" onClick={onCommand} aria-label="Commands" aria-keyshortcuts="Meta+K" className="hidden gap-1 text-muted-foreground sm:inline-flex">
        <IconSearch aria-hidden />
        <kbd className="flex items-center font-sans text-xs">
          <IconCommand className="size-3!" aria-hidden />K
        </kbd>
      </Button>
      <Button variant="ghost" size="icon-sm" onClick={onCommand} aria-label="Commands" className="sm:hidden">
        <IconSearch aria-hidden />
      </Button>
      <Settings />
      <ThemeToggle />
    </div>
  );
}

function Accounts(): React.JSX.Element {
  const { state, queueWrite, writes, down, busy } = useBoard();
  const pool = poolOf(state);
  const installed = Object.entries(state.installed);
  const off = down || busy;
  const toggle = (name: string, on: boolean): void => {
    const names = on ? [...pool.filter((n) => n !== name), name] : pool.filter((n) => n !== name);
    if (names.length === 0) {
      say({ ok: false, words: "keep at least one account for the run" });
      return;
    }
    void queueWrite("POST /api/queue/agents", { names, version: state.queue.version }, `The run uses ${names.join(", ")}.`);
  };
  const trouble = installed.some(([n, e]) => pool.includes(n) && accountState(n, e, state).tone === "out");
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" aria-label={`${pool.join(", ") || "No accounts"}: the run's accounts`} className={cn("max-w-48", trouble && "border-destructive/50 text-destructive")}>
          <IconRobot aria-hidden />
          <span className="hidden truncate sm:inline">{pool.length > 0 ? pool.join(", ") : "No accounts"}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <p className="mb-2 text-sm font-medium">The run's accounts</p>
        {installed.length === 0 ? (
          <p className="text-sm text-muted-foreground">No agents found yet.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {installed.map(([n, e]) => {
              const st = accountState(n, e, state);
              const u = st.tone === "out" ? null : usageOf(e, state.now);
              return (
                <li key={n}>
                  <label className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-accent">
                    <input
                      type="checkbox"
                      className="size-4 accent-[var(--brand)]"
                      checked={pool.includes(n)}
                      disabled={off}
                      onChange={(ev) => {
                        toggle(n, ev.currentTarget.checked);
                      }}
                    />
                    <span className="font-medium">{n}</span>
                    {e.kind === "agy" && <span className="text-xs text-muted-foreground">emergencies</span>}
                    {e.kind === "codex" && <span className="text-xs text-muted-foreground">Codex</span>}
                    <span className={cn("ml-auto text-xs", st.tone === "out" ? "text-destructive" : st.tone === "lim" ? "text-warn" : st.tone === "run" ? "text-brand" : "text-muted-foreground")}>
                      {u ? `${String(u.pct)}% · ` : ""}
                      {st.words}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
        <Button
          variant="ghost"
          size="xs"
          className="mt-2 w-full"
          disabled={off}
          onClick={() => {
            void writes.scan().then(say);
          }}
        >
          Scan for agents
        </Button>
      </PopoverContent>
    </Popover>
  );
}

/** When the run should finish: a chip you only read, and a popover with each map's finish and how it was worked out. */
function EtaChip(): React.JSX.Element | null {
  const { state, ix, tickets } = useBoard();
  const end = endsAt(state, ix);
  if (end <= 0 || state.queue.night === null) return null;
  const nameOf = (map: string): string => {
    const t = tickets?.find((x) => x.map === map);
    return map === "" ? "Jobs" : t === undefined ? map : mapTitle(t);
  };
  const etas = mapEtas(state, ix);
  const slots = Object.keys(state.queue.repos ?? {}).length;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" data-testid="eta-chip" title="When the run should finish" aria-label={`Done ~${hm(end)}`}>
          <IconClock aria-hidden />
          <span className="hidden md:inline">Done ~{hm(end)}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <div className="flex flex-col gap-2 text-sm">
          <p className="font-medium">The run should be done about {hm(end)}</p>
          <ul data-testid="eta-maps" className="flex flex-col gap-1.5">
            {etas.map((e) => (
              <li key={e.map} data-testid="eta-map" className="flex flex-col">
                <span className="flex items-baseline justify-between gap-2">
                  <span className="truncate font-medium">{nameOf(e.map)}</span>
                  <span className="tabular-nums">~{hm(e.end)}</span>
                </span>
                <span className="text-xs text-muted-foreground">
                  {e.queued > 0 ? `${plural(e.queued, "ticket")} queued` : "running now"} at {Math.round(e.minutes)} min each, {e.measured ? "as the finished ones took" : "no finished ticket to go by"}; {e.atOnce} at once
                </span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">
            Each ticket is reckoned at the middle time of its map's finished tickets, 90 minutes when there are none. {slots > 1 ? "Repos run side by side, so the run ends with the latest." : ""}
          </p>
        </div>
      </PopoverContent>
    </Popover>
  );
}

const LAYOUTS: readonly [GraphLayout, string, string][] = [
  ["vertical", "Vertical", "Time runs down; a ticket's box is as tall as its run took."],
  ["horizontal", "Horizontal", "Time runs across; a ticket's box is as wide as its run took."],
];

/** The board's settings, for this browser: how the run's graph and a map's graph are laid out. */
function Settings(): React.JSX.Element {
  const layout = useGraphLayout();
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="Settings" title="Settings">
          <IconSettings aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72">
        <div role="radiogroup" aria-label="Graph layout" className="flex flex-col gap-1.5">
          <p className="text-sm font-semibold">Graph layout</p>
          {LAYOUTS.map(([value, label, hint]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={layout === value}
              onClick={() => {
                setGraphLayout(value);
              }}
              className={cn(
                "flex flex-col items-start gap-0.5 rounded-md border px-2.5 py-1.5 text-left text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                layout === value ? "border-brand bg-brand/10" : "hover:bg-muted",
              )}
            >
              <span className="font-medium">{label}</span>
              <span className="text-xs text-muted-foreground">{hint}</span>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function ThemeToggle(): React.JSX.Element {
  const theme = useTheme();
  const dark = theme === "dark" || (theme === "system" && document.documentElement.classList.contains("dark"));
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={dark ? "Use the light theme" : "Use the dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
      onClick={() => {
        setTheme(dark ? "light" : "dark");
      }}
    >
      {dark ? <IconSun aria-hidden /> : <IconMoon aria-hidden />}
    </Button>
  );
}
