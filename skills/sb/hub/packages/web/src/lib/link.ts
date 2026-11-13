/** The page link holds the view, the filters and the open ticket, so a reload or a shared link opens the same board. */
import { useSyncExternalStore } from "react";
import { SHOWS, type Show } from "./board.ts";
import { Store } from "./store.ts";

/** Runs is the landing view. A Sessions tab comes later (ticket 044). */
export const VIEWS = ["runs", "queue", "waits"] as const;
export type View = (typeof VIEWS)[number];
export const DEFAULT_VIEW: View = "runs";

export interface Link {
  readonly view: View;
  /** The Queue's search: words, a project, a map, and which open tickets. */
  readonly q: string;
  readonly p: string;
  readonly m: string;
  readonly s: Show;
  /** The open ticket's key, "p:<path>" for a project, or "". */
  readonly t: string;
}

const KEYS = ["view", "q", "p", "m", "s", "t"] as const;

export function readLink(search: string): Link {
  const s = new URLSearchParams(search);
  const v = s.get("view");
  const show = s.get("s");
  return {
    view: VIEWS.find((x) => x === v) ?? DEFAULT_VIEW,
    q: s.get("q") ?? "",
    p: s.get("p") ?? "",
    m: s.get("m") ?? "",
    s: SHOWS.find((x) => x === show) ?? "ready",
    t: s.get("t") ?? "",
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
  const pChanged = change.p !== undefined && change.p !== now.p && change.m === undefined;
  const next: Link = { ...now, ...change, ...(pChanged ? { m: "" } : {}) };
  history.replaceState(null, "", `${location.pathname}${writeLink(next)}${location.hash}`);
  link.set(next);
}

export function useLink(): Link {
  return useSyncExternalStore(subscribe, link.get, link.get);
}
