/** The graph layout setting: the run's graph and a map's graph run vertically (time down) or horizontally (time
 * across). Kept in localStorage for this browser; vertical until another is chosen. */
import { useSyncExternalStore } from "react";
import { Store } from "./store.ts";

export type GraphLayout = "vertical" | "horizontal";
const KEY = "sbhub.graphLayout";

function stored(): GraphLayout {
  try {
    return typeof window !== "undefined" && localStorage.getItem(KEY) === "horizontal" ? "horizontal" : "vertical";
  } catch {
    return "vertical";
  }
}
const layout = new Store<GraphLayout>(stored());

export function setGraphLayout(l: GraphLayout): void {
  try {
    localStorage.setItem(KEY, l);
  } catch {
    /* a private window: this view only */
  }
  layout.set(l);
}

export function useGraphLayout(): GraphLayout {
  return useSyncExternalStore(layout.subscribe, layout.get, layout.get);
}
