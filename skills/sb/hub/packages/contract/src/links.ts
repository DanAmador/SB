/**
 * The obsidian:// links the API carries on every ticket row and queue item. The hub runs next to the vault, so a ticket's
 * text, report, log, run board and map open in Obsidian instead of being copied into the board.
 * `obsidianUri` builds them the way `sbmap uri` does (the absolute path, fully encoded); links.test.ts holds it to sbmap's output.
 */
import { z } from "zod";

/** Python's urllib.parse.quote(path, safe="") leaves letters, digits and _.-~ alone; encodeURIComponent also leaves !'()*. */
const enc = (s: string): string => encodeURIComponent(s).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);

/** The vault as Obsidian knows it: its folder on this Mac (symlinks resolved) and its name, which a phone's vault shares. */
export interface Vault {
  readonly root: string;
  readonly name: string;
}

/**
 * With a vault, a note inside it links by the vault's name and its path in the vault, so the same link opens on a phone
 * whose vault has that name; any other file (or no vault) links by its absolute path, as `sbmap uri` does.
 */
export function obsidianUri(path: string, vault?: Vault): string {
  if (vault !== undefined && path.startsWith(`${vault.root}/`)) {
    return `obsidian://open?vault=${enc(vault.name)}&file=${enc(path.slice(vault.root.length + 1))}`;
  }
  return `obsidian://open?path=${enc(path)}`;
}

/** An `obsidian://open?path=` link (what the Python hub writes) as a link by vault name; anything else is left alone. */
export function vaultUri(uri: string, vault: Vault): string {
  const m = /^obsidian:\/\/open\?path=([^&]*)$/.exec(uri);
  if (m === null) return uri;
  try {
    return obsidianUri(decodeURIComponent(m[1] ?? ""), vault);
  } catch {
    return uri;
  }
}

const Uri = z.string().regex(/^obsidian:\/\/open\?(?:path=%2F|vault=[^&]+&file=)/).nullable();

/** One link per vault note around a ticket; null where the note does not exist (yet). */
export const Links = z.strictObject({
  ticket: Uri,
  map: Uri,
  /** Tonight's run board of its map. */
  board: Uri,
  report: Uri,
  log: Uri,
});
export type Links = z.infer<typeof Links>;

/** What link building needs from the disk and from earlier answers. */
export interface LinkContext {
  exists: (path: string) => boolean;
  /** The path with symlinks resolved, which is what `sbmap uri` links (Path.resolve). */
  real: (path: string) => string;
  /** The ticket note of `map#num`, open or done, or null. */
  findTicket: (map: string, num: number) => string | null;
  /** Map -> its run board, as the queue last gave them: a ticket row has no queue of its own. */
  runs: Record<string, string>;
  /** Set, every link names the vault instead of the Mac's path. */
  vault?: Vault;
}

const linkTo = (path: string | null | undefined, ctx: LinkContext): string | null =>
  path?.startsWith("/") === true && ctx.exists(path) ? obsidianUri(ctx.real(path), ctx.vault) : null;

/** A ticket file's map: wayfinder/<repo>/<effort>/issues/[done/]NNN.md -> wayfinder/<repo>/<effort>/map.md. */
export function mapNote(ticketFile: string): string | null {
  const m = /^(.*)\/issues\/(?:done\/)?[^/]+$/.exec(ticketFile);
  return m ? `${m[1] ?? ""}/map.md` : null;
}

interface ItemLike {
  readonly key: string;
  readonly kind: "ticket" | "job";
  readonly map?: string | undefined;
  readonly run?: string | undefined;
  readonly log?: string | undefined;
  readonly result?: string | undefined;
}

const keyParts = (key: string): { map: string; num: number } | null => {
  const m = /^(.+)#(\d+)$/.exec(key);
  return m ? { map: m[1] ?? "", num: Number(m[2]) } : null;
};

/** The links of one queue item: a ticket's note and map, its map's run board, its worker's report and log. */
export function itemLinks(i: ItemLike, ctx: LinkContext): Links {
  const k = keyParts(i.key);
  if (i.kind === "job" || k === null) return { ticket: null, map: null, board: null, report: linkTo(i.result, ctx), log: linkTo(i.log, ctx) };
  const ticket = ctx.findTicket(k.map, k.num);
  const report = i.run !== undefined ? `${i.run}/${String(k.num)}.md` : null;
  return {
    ticket: linkTo(ticket, ctx),
    map: linkTo(ticket === null ? null : mapNote(ticket), ctx),
    board: linkTo(ctx.runs[i.map ?? k.map], ctx),
    report: linkTo(report, ctx),
    log: linkTo(i.log, ctx),
  };
}

/** The links of one open ticket row: its note and map, and its map's run board (it has no run of its own). */
export function rowLinks(r: { readonly map: string; readonly file: string }, ctx: LinkContext): Links {
  return { ticket: linkTo(r.file, ctx), map: linkTo(mapNote(r.file), ctx), board: linkTo(ctx.runs[r.map], ctx), report: null, log: null };
}
