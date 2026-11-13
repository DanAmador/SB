/** Where the hub listens and keeps its state, read as sbhub.py reads them. */
import { homedir } from "node:os";
import { join } from "node:path";

export const DEFAULT_PORT = 8765;

const valid = (n: number): boolean => Number.isInteger(n) && n > 0 && n < 65536;

/** --port N, else SB_HUB_PORT, else 8765; a value that is not a port falls back to 8765, as in sbhub.py. */
export function hubPort(argv: readonly string[], env: Readonly<Record<string, string | undefined>>): number {
  const i = argv.indexOf("--port");
  const given = i >= 0 ? argv[i + 1] : env.SB_HUB_PORT;
  if (given === undefined || given === "") return DEFAULT_PORT;
  const n = Number(given);
  return valid(n) ? n : DEFAULT_PORT;
}

export function hubHome(env: Readonly<Record<string, string | undefined>>): string {
  const h = env.SB_HUB_HOME;
  return h !== undefined && h !== "" ? h : join(homedir(), ".sb-hub");
}
