/**
 * A value outside React that components read with useSyncExternalStore. A class, so the React compiler (set to
 * compile every function) sees method calls, never a module variable reassigned.
 */
export class Store<T> {
  private listeners = new Set<() => void>();
  constructor(private value: T) {}
  readonly get = (): T => this.value;
  readonly subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };
  set(value: T): void {
    this.value = value;
    for (const fn of this.listeners) fn();
  }
}
