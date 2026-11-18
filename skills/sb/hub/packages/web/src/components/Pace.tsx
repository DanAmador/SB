/** Usage pace: one toolbar button; per account, what is used, held by running work and free, and whether the week lasts. */
import { IconGauge } from "@tabler/icons-react";
import type * as React from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { hm } from "@/lib/board.ts";
import { GATE_5H, GATE_7D, poolPace, type AccountPace, type PoolPace, type WeekPace } from "@/lib/pace.ts";
import { cn } from "@/lib/utils";
import { useBoard } from "./context.tsx";

const pct = (x: number): string => `${String(Math.round(100 * x))}%`;
const dayHm = (ts: number): string => `${new Date(ts * 1000).toLocaleDateString(undefined, { weekday: "short" })} ${hm(ts)}`;
const days = (seconds: number): string => {
  const d = seconds / 86400;
  return d >= 1 ? `${d.toFixed(d >= 10 ? 0 : 1)} days` : `${String(Math.max(1, Math.round(seconds / 3600)))} h`;
};

export function Pace(): React.JSX.Element {
  const { state } = useBoard();
  const p = poolPace(state);
  const label = p.top === null ? "Usage" : pct(p.top);
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" aria-label={`Usage: ${p.top === null ? "no reading yet" : `${pct(p.top)} of five hours used`}`} className={cn(p.tight && "border-warn/60 text-warn")}>
          <IconGauge aria-hidden />
          <span className="hidden sm:inline">{label}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="max-h-[80vh] w-[min(22rem,calc(100vw-1rem))] overflow-y-auto">
        <p className="text-sm font-medium">Usage</p>
        <p className="mt-1 text-xs text-muted-foreground">{poolWords(p)}</p>
        {p.accounts.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">No agents found yet.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-4">
            {p.accounts.map((a) => (
              <li key={a.name}>
                <Account a={a} now={state.now} />
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 border-t pt-2 text-xs text-muted-foreground">
          The hub starts nothing that would pass {pct(GATE_5H)} of five hours or {pct(GATE_7D)} of the week.
        </p>
      </PopoverContent>
    </Popover>
  );
}

/** One line for tonight's accounts together: what the line needs against what is free. */
function poolWords(p: PoolPace): string {
  if (p.top === null) return "No usage reading for the accounts in use yet.";
  const until = `${p.inUse > 1 ? ` across ${String(p.inUse)} accounts` : ""}${p.resets !== null ? ` until ${hm(p.resets)}` : ""}`;
  if (p.queued === 0) return `Nothing in line. ${pct(p.free)} of five hours is free${until}.`;
  const line = `${String(p.queued)} in line need about ${pct(p.need)} of five hours`;
  if (p.need > p.free) return `${line}, more than the ${pct(p.free)} free: the rest waits for the reset${p.resets !== null ? ` at ${hm(p.resets)}` : ""}.`;
  return `${line}; ${pct(p.free)} is free${until}. About ${pct(p.unused)} will go unused.`;
}

function fitsWords(fits: NonNullable<AccountPace["five"]>["fits"]): string {
  if ("tickets" in fits) {
    if (fits.tickets === null) return "No ticket estimate yet: it is learned from this account's first finished tickets.";
    return fits.tickets === 0 ? "No room for another ticket before the reset." : `Room for about ${String(fits.tickets)} more tickets.`;
  }
  return fits.sonnet === 0
    ? "No room for another ticket before the reset."
    : `Room for about ${String(fits.sonnet)} more Sonnet tickets${fits.opus > 0 ? ` or ${String(fits.opus)} Opus` : ""}.`;
}

function Account({ a, now }: { a: AccountPace; now: number }): React.JSX.Element {
  const f = a.five;
  return (
    <div className="flex flex-col gap-1.5 text-sm">
      <div className="flex items-baseline gap-2">
        <span className="font-medium">{a.name}</span>
        <span className="text-xs text-muted-foreground">{a.inPool ? "tonight" : a.running > 0 ? "not one of tonight's, but running" : "not in tonight's accounts"}</span>
        {a.running > 0 && <span className="ml-auto text-xs text-brand">{String(a.running)} running</span>}
      </div>
      {f === null ? (
        <p className="text-xs text-muted-foreground">No usage reading.</p>
      ) : (
        <>
          <Bar
            label={`Five hours: ${pct(f.used)} used, ${pct(f.held)} held by running work, ${pct(f.free)} free`}
            parts={[
              [f.used, "bg-brand"],
              [f.held, "bg-brand/40"],
            ]}
            gate={GATE_5H}
          />
          <p className="text-xs text-muted-foreground">
            <span className="text-foreground">{pct(f.used)} used</span>
            {f.held >= 0.005 && <> · {pct(f.held)} held by running work</>} · {pct(f.free)} free · {f.resets !== null ? `resets ${hm(f.resets)}` : "a new five hours"}
          </p>
          <p className="text-xs text-muted-foreground">
            {fitsWords(f.fits)}
          </p>
          {f.old && <p className="text-xs text-warn">Last read {hm(f.at)}: too old to go by, so only one worker starts here until a new reading.</p>}
          {a.week && <Week w={a.week} now={now} />}
        </>
      )}
    </div>
  );
}

function Week({ w, now }: { w: WeekPace; now: number }): React.JSX.Element {
  const early = w.stopped || w.stopsAt !== null;
  return (
    <>
      <Bar label={`Week: ${pct(w.used)} used, ${pct(w.gone)} of the week gone`} parts={[[w.used, early ? "bg-warn" : "bg-brand"]]} gate={GATE_7D} mark={w.even} />
      <p className={cn("text-xs", early ? "text-warn" : "text-muted-foreground")}>
        Week: {pct(w.used)} used with {pct(w.gone)} of it gone.{" "}
        {w.stopped
          ? `Past its ${pct(GATE_7D)} stop: nothing starts here until ${dayHm(w.resets)}.`
          : w.stopsAt !== null
            ? `At this rate it reaches its ${pct(GATE_7D)} stop ${dayHm(w.stopsAt)}, ${days(w.resets - w.stopsAt)} before it resets ${dayHm(w.resets)}.`
            : `It lasts at this rate (resets ${dayHm(w.resets)}).`}
        {!w.stopped && w.stopsAt !== null && ` To last, about ${pct(((GATE_7D - w.used) / (w.resets - now)) * 86400)} a day.`}
      </p>
    </>
  );
}

/** A thin bar: filled parts from the left, a line at the gate, and an optional mark (where an even pace would stand). */
function Bar({ label, parts, gate, mark }: { label: string; parts: [number, string][]; gate: number; mark?: number }): React.JSX.Element {
  const at = (x: number): string => `${String(Math.min(100, Math.max(0, 100 * x)))}%`;
  return (
    <div role="img" aria-label={label} className="relative h-2 overflow-hidden rounded-full bg-muted">
      <div className="flex h-full">
        {parts.map(([share, cls]) => (
          <div key={cls} className={cls} style={{ width: at(share) }} />
        ))}
      </div>
      {mark !== undefined && <div className="absolute inset-y-0 w-0.5 bg-foreground/60" style={{ left: at(mark) }} title="An even pace would stand here" />}
      <div className="absolute inset-y-0 w-px bg-destructive" style={{ left: at(gate) }} title={`The hub's stop at ${pct(gate)}`} />
    </div>
  );
}
