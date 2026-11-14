/** The page link holds the view, the filters and the open ticket, so a reload or a shared link opens the same board. */
import { useSyncExternalStore } from "react";
import { SHOWS, type Show } from "./board.ts";
import { Store } from "./store.ts";

/** Runs is the landing view. Sessions (ticket 044) is key 4 and comes later; History is key 5. */
export const VIEWS = ["runs", "queue", "waits", "history"] as const;
export type View = (typeof VIEWS)[number];
export const DEFAULT_VIEW: View = "runs";

export interface Link {
  readonly view: View;
  /** The Queue's search words, and which open tickets. */
  readonly q: string;
  /** The sidebar's pick: a project, and one of its maps. Both empty is Everything. */
  readonly project: string;
  readonly map: string;
  readonly s: Show;
  /** The open ticket's key, "p:<path>" for a project, or "". */
  readonly t: string;
  /** History: the open run's key, and the open picture's name. */
  readonly run: string;
  readonly pic: string;
  /** History's filters: time range, outcome, has pictures ("1"), account, model. */
  readonly range: string;
  readonly out: string;
  readonly pics: string;
  readonly acct: string;
  readonly model: string;
}

const KEYS = ["view", "q", "project", "map", "s", "t", "run", "pic", "range", "out", "pics", "acct", "model"] as const;

export function readLink(search: string): Link {
  const s = new URLSearchParams(search);
  const v = s.get("view");
  const show = s.get("s");
  return {
    view: VIEWS.find((x) => x === v) ?? DEFAULT_VIEW,
    q: s.get("q") ?? "",
    project: s.get("project") ?? "",
    map: s.get("map") ?? "",
    s: SHOWS.find((x) => x === show) ?? "ready",
    t: s.get("t") ?? "",
    run: s.get("run") ?? "",
    pic: s.get("pic") ?? "",
    range: s.get("range") ?? "",
    out: s.get("out") ?? "",
    pics: s.get("pics") ?? "",
    acct: s.get("acct") ?? "",
    model: s.get("model") ?? "",
  };
}

export function writeLink(link: Link): string {
  const s = new URLSearchParams();
  for (const k of KEYS) {
    const v = link[k];
    if (v && !(k === "view" && v === DEFAULT_VIEW) && !(k === "s" && v === "ready")) s.set(k, v);
  }
  const qs = s.toString();
  return qs ? `?${qs}` : "";
}

const link = new Store<Link>(typeof location === "undefined" ? readLink("") : readLink(location.search));

function subscribe(fn: () => void): () => void {
  const off = link.subscribe(fn);
  const pop = (): void => {
    link.set(readLink(location.search));
  };
  window.addEventListener("popstate", pop);
  return () => {
    off();
    window.removeEventListener("popstate", pop);
  };
}

export function setLink(change: Partial<Link>): void {
  const now = link.get();
  // a new project drops the map, which belonged to the old one
  const pChanged = change.project !== undefined && change.project !== now.project && change.map === undefined;
  const next: Link = { ...now, ...change, ...(pChanged ? { map: "" } : {}) };
  history.replaceState(null, "", `${location.pathname}${writeLink(next)}${location.hash}`);
  link.set(next);
}

export function useLink(): Link {
  return useSyncExternalStore(subscribe, link.get, link.get);
}
