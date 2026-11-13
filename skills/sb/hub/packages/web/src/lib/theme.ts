/** Light, dark, or the system's: kept in localStorage, applied as the html element's dark class. */
import { useEffect, useSyncExternalStore } from "react";
import { Store } from "./store.ts";

export type Theme = "light" | "dark" | "system";
const KEY = "sbhub.theme";
const media = (): MediaQueryList | null => (typeof matchMedia === "function" ? matchMedia("(prefers-color-scheme: dark)") : null);

function read(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}
function stored(): Theme {
  const v = typeof window === "undefined" ? null : read();
  return v === "light" || v === "dark" ? v : "system";
}
const theme = new Store<Theme>(stored());

export function applyTheme(): void {
  const t = theme.get();
  const dark = t === "dark" || (t === "system" && media()?.matches === true);
  document.documentElement.classList.toggle("dark", dark);
}

function write(t: Theme): void {
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* a private window: this view only */
  }
}

export function setTheme(t: Theme): void {
  write(t);
  theme.set(t);
  applyTheme();
}

/** The chosen theme; the page follows the system's while none is chosen. */
export function useTheme(): Theme {
  useEffect(() => {
    const m = media();
    m?.addEventListener("change", applyTheme);
    return () => {
      m?.removeEventListener("change", applyTheme);
    };
  }, []);
  return useSyncExternalStore(theme.subscribe, theme.get, theme.get);
}
