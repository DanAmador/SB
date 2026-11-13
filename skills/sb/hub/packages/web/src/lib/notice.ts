/** The page's feedback after a write: shown a few seconds, read out by screen readers. */
import { useSyncExternalStore } from "react";
import type { Outcome } from "./hub.ts";
import { Store } from "./store.ts";

export type Notice = Readonly<{ id: number; ok: boolean; words: string }>;

const notices = new Store<readonly Notice[]>([]);
const ids = new Store(1);

export function say(o: Outcome): void {
  const n: Notice = { id: ids.get(), ok: o.ok, words: o.ok ? o.words : `Not done: ${o.words}` };
  ids.set(n.id + 1);
  notices.set([...notices.get().slice(-2), n]);
  setTimeout(
    () => {
      notices.set(notices.get().filter((x) => x.id !== n.id));
    },
    o.ok ? 4000 : 9000,
  );
}

export function useNotices(): readonly Notice[] {
  return useSyncExternalStore(notices.subscribe, notices.get, notices.get);
}
