/**
 * The ended runs the owner has looked at ("Looks good", "Set aside"), kept in this browser. The hub has no route for
 * it yet, so another browser shows them again; nothing in the vault changes.
 */
import { useSyncExternalStore } from "react";
import { Store } from "./store.ts";

const KEY = "sb-hub-seen";
/** Older keys drop off once there are this many. */
const KEEP = 500;

function read(): ReadonlySet<string> {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return new Set(Array.isArray(raw) ? raw.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

const seen = new Store<ReadonlySet<string>>(typeof localStorage === "undefined" ? new Set() : read());

export function markSeen(key: string): void {
  const next = [...seen.get(), key].slice(-KEEP);
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // private mode: it is remembered until the page reloads
  }
  seen.set(new Set(next));
}

export function useSeen(): ReadonlySet<string> {
  return useSyncExternalStore(seen.subscribe, seen.get, seen.get);
}
