/** The sidebar's tree: per map and project, what can run now and what is queued; a running dot; quiet maps folded. Pure. */
import type { QueueItem, State, TicketRow } from "@sb-hub/contract";
import { folder, itemMapKey, projOf, tkey, type Scope } from "./board.ts";

export interface Counts {
  /** Tickets in state ready that are not yet in line. */
  readonly canRun: number;
  /** Tickets in line: queued, or running. */
  readonly queued: number;
  /** A worker is running here. */
  readonly running: boolean;
}
export interface SidebarMap extends Counts {
  readonly map: string;
  readonly title: string;
  /** Its tickets cannot run only because the map has no checks. */
  readonly noChecks: boolean;
}
export interface SidebarProject extends Counts {
  readonly project: string;
  /** The maps with work, running, or picked. */
  readonly maps: readonly SidebarMap[];
  /** The maps folded under "N quiet maps". */
  readonly quiet: readonly SidebarMap[];
}
export interface Sidebar {
  readonly all: Counts;
  readonly projects: readonly SidebarProject[];
}

const NO_CHECKS = "no check commands";
const isQuiet = (c: Counts): boolean => c.canRun === 0 && c.queued === 0 && !c.running;

export function sidebarTree(state: State, tickets: readonly TicketRow[] | null, scope: Scope): Sidebar {
  const live = new Set<string>();
  for (const i of state.queue.items) if (i.state === "queued" || i.state === "running") live.add(i.key);
  const proj = new Map<string, Set<string>>();
  const see = (project: string, map: string): void => {
    if (project === "") return;
    const set = proj.get(project) ?? new Set<string>();
    if (map !== "") set.add(map);
    proj.set(project, set);
  };
  const canRun = new Map<string, number>();
  const noChecks = new Map<string, number>();
  const inLine = new Map<string, number>();
  const runs = new Map<string, number>();
  const titles = new Map<string, string>();
  const bump = (m: Map<string, number>, k: string): void => {
    m.set(k, (m.get(k) ?? 0) + 1);
  };
  const jobProject = (i: QueueItem): string => folder(i.kind === "job" ? i.project : undefined);
  for (const t of tickets ?? []) {
    see(projOf(t.map), t.map);
    titles.set(t.map, t.map.split("/").pop() ?? t.map);
    if (t.state === "ready" && !live.has(tkey(t))) bump(canRun, t.map);
    if (t.reason === NO_CHECKS) bump(noChecks, t.map);
  }
  const jobsLine = new Map<string, number>();
  const jobsRun = new Map<string, number>();
  for (const i of state.queue.items) {
    if (i.state !== "queued" && i.state !== "running") continue;
    const map = itemMapKey(i);
    const project = map === "" ? jobProject(i) : projOf(map);
    see(project, map);
    if (map === "") {
      bump(jobsLine, project);
      if (i.state === "running") bump(jobsRun, project);
    } else {
      bump(inLine, map);
      if (i.state === "running") bump(runs, map);
    }
  }
  const mapRow = (map: string): SidebarMap => {
    const c = canRun.get(map) ?? 0;
    return {
      map,
      title: titles.get(map) ?? map.split("/").pop() ?? map,
      canRun: c,
      queued: inLine.get(map) ?? 0,
      running: (runs.get(map) ?? 0) > 0,
      noChecks: c === 0 && (noChecks.get(map) ?? 0) > 0,
    };
  };
  const projects = [...proj.entries()]
    .sort(([x], [y]) => x.localeCompare(y))
    .map(([project, maps]): SidebarProject => {
      const rows = [...maps].sort((x, y) => x.localeCompare(y)).map(mapRow);
      const shown = (m: SidebarMap): boolean => !isQuiet(m) || m.map === scope.map;
      return {
        project,
        canRun: rows.reduce((n, m) => n + m.canRun, 0),
        queued: rows.reduce((n, m) => n + m.queued, 0) + (jobsLine.get(project) ?? 0),
        running: rows.some((m) => m.running) || (jobsRun.get(project) ?? 0) > 0,
        maps: rows.filter(shown),
        quiet: rows.filter((m) => !shown(m)),
      };
    });
  return {
    all: {
      canRun: projects.reduce((n, p) => n + p.canRun, 0),
      queued: projects.reduce((n, p) => n + p.queued, 0),
      running: state.queue.items.some((i) => i.state === "running"),
    },
    projects,
  };
}
