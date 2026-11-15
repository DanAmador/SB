/** The sidebar's tree: per map and project, what can run now and what is queued; a running dot; every map in one list, busiest first. Pure. */
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
  /** Why a map with open tickets has nothing to run or queue, in a few words; "" when it is busy or has no open tickets. */
  readonly reason: string;
}
export interface SidebarProject extends Counts {
  readonly project: string;
  /** Every map: running, can run, queued, stuck, then nothing left; ties by name. */
  readonly maps: readonly SidebarMap[];
}
export interface Sidebar {
  readonly all: Counts;
  readonly projects: readonly SidebarProject[];
}

const NO_CHECKS = "no check commands";
const isActive = (c: Counts): boolean => c.queued > 0 || c.running;

/** Only what is in play: the projects and maps with something queued or running. A picked project or map stays shown. */
export function activeOnly(tree: Sidebar, scope: Scope): Sidebar {
  const projects = tree.projects
    .filter((p) => isActive(p) || p.project === scope.project)
    .map((p): SidebarProject => ({ ...p, maps: p.maps.filter((m) => isActive(m) || m.map === scope.map) }));
  return { all: tree.all, projects };
}

// ponytail: scope is unused now (every map is listed); Board.tsx, not mine to edit here, still passes it.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function sidebarTree(state: State, tickets: readonly TicketRow[] | null, _scope?: Scope): Sidebar {
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
  const open = new Map<string, number>();
  const waits = new Map<string, number>();
  const claimed = new Map<string, number>();
  const bump = (m: Map<string, number>, k: string): void => {
    m.set(k, (m.get(k) ?? 0) + 1);
  };
  const jobProject = (i: QueueItem): string => folder(i.kind === "job" ? i.project : undefined);
  for (const t of tickets ?? []) {
    see(projOf(t.map), t.map);
    titles.set(t.map, t.map.split("/").pop() ?? t.map);
    if (t.state === "ready" && !live.has(tkey(t))) bump(canRun, t.map);
    bump(open, t.map);
    if (t.state === "waits for you") bump(waits, t.map);
    if (t.state === "claimed") bump(claimed, t.map);
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
    const q = inLine.get(map) ?? 0;
    const stuck = c === 0 && q === 0 && (runs.get(map) ?? 0) === 0 && (open.get(map) ?? 0) > 0;
    const noC = c === 0 && (noChecks.get(map) ?? 0) > 0;
    let reason = "";
    if (stuck) reason = noC ? "no checks" : waits.has(map) ? "waits for you" : claimed.has(map) ? "claimed" : "blocked";
    return {
      map,
      title: titles.get(map) ?? map.split("/").pop() ?? map,
      canRun: c,
      queued: inLine.get(map) ?? 0,
      running: (runs.get(map) ?? 0) > 0,
      noChecks: noC,
      reason,
    };
  };
  const projects = [...proj.entries()]
    .sort(([x], [y]) => x.localeCompare(y))
    .map(([project, maps]): SidebarProject => {
      const rank = (m: SidebarMap): number => (m.running ? 0 : m.canRun > 0 ? 1 : m.queued > 0 ? 2 : m.reason !== "" ? 3 : 4);
      const rows = [...maps].sort((x, y) => x.localeCompare(y)).map(mapRow).sort((x, y) => rank(x) - rank(y)); // stable: ties stay by name
      return {
        project,
        canRun: rows.reduce((n, m) => n + m.canRun, 0),
        queued: rows.reduce((n, m) => n + m.queued, 0) + (jobsLine.get(project) ?? 0),
        running: rows.some((m) => m.running) || (jobsRun.get(project) ?? 0) > 0,
        maps: rows,
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
