/** The vault on disk, for the links the API carries: where a ticket note is, and whether a file is there. */
import { existsSync, readdirSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { basename, join } from "node:path";
import type { LinkContext } from "@sb-hub/contract";

/** SB_VAULT, as sbmap and sbhub.py read it, else ~/Documents/Second Brain. */
export const vaultDir = (env: Readonly<Record<string, string | undefined>>): string => env.SB_VAULT ?? join(homedir(), "Documents", "Second Brain");

/** wayfinder/<map>/issues/[done/]NNN[ -]*.md, the first by name, as sbhub.py's _ticket_file finds it. */
export function findTicket(vault: string, map: string, num: number): string | null {
  if (map.split("/").some((p) => p === "" || p === "." || p === "..")) return null;
  const issues = join(vault, "wayfinder", map, "issues");
  const prefix = String(num).padStart(3, "0");
  for (const dir of [issues, join(issues, "done")]) {
    let names: string[];
    try {
      names = readdirSync(dir);
    } catch {
      continue;
    }
    const hit = names.filter((n) => n.endsWith(".md") && (n.startsWith(`${prefix} `) || n.startsWith(`${prefix}-`))).sort()[0];
    if (hit !== undefined) return join(dir, hit);
  }
  return null;
}

export const linkContext = (vault: string): LinkContext => ({
  exists: existsSync,
  real: (p) => realpathSync(p),
  findTicket: (map, num) => findTicket(vault, map, num),
  runs: {},
  vault: ((root) => ({ root, name: basename(root) }))(existsSync(vault) ? realpathSync(vault) : vault),
});
