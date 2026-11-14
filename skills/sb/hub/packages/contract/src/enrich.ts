/** Adds `links` to the Python hub's answers: the one place the public API differs from what sbhub.py sends. */
import { itemLinks, rowLinks, vaultUri, type LinkContext, type Vault } from "./links.ts";
import type { RouteName } from "./routes.ts";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);

function linkQueue(q: unknown, ctx: LinkContext): unknown {
  if (!isObj(q)) return q;
  if (isObj(q.runs)) {
    for (const [map, board] of Object.entries(q.runs)) if (typeof board === "string") ctx.runs[map] = board;
  }
  const items = (list: unknown): unknown =>
    Array.isArray(list) ? list.map((i: unknown) => (isObj(i) && typeof i.key === "string" ? { ...i, links: itemLinks(i as unknown as Parameters<typeof itemLinks>[0], ctx) } : i)) : list;
  return { ...q, items: items(q.items), ...(q.cleared === undefined ? {} : { cleared: items(q.cleared) }) };
}

/** Every obsidian:// path link in `v` (the ticket's `uri` and `map_uri`, its trail's) as a link by vault name. */
function renameLinks(v: unknown, vault: Vault): unknown {
  if (typeof v === "string") return v.startsWith("obsidian://") ? vaultUri(v, vault) : v;
  if (Array.isArray(v)) return v.map((x: unknown) => renameLinks(x, vault));
  if (isObj(v)) return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, renameLinks(x, vault)]));
  return v;
}

/**
 * `body` as the Python hub answered `route`, with `links` on every queue item and ticket row in it. `ctx.runs` learns each
 * map's run board from any queue it sees, so a ticket row (which has no queue) can link its board too.
 */
export function addLinks(route: RouteName, body: unknown, ctx: LinkContext): unknown {
  const out = addRowLinks(route, body, ctx);
  return ctx.vault === undefined ? out : renameLinks(out, ctx.vault);
}

function addRowLinks(route: RouteName, body: unknown, ctx: LinkContext): unknown {
  if (route === "GET /api/tickets" && Array.isArray(body)) {
    return body.map((r: unknown) => (isObj(r) && typeof r.map === "string" && typeof r.file === "string" ? { ...r, links: rowLinks({ map: r.map, file: r.file }, ctx) } : r));
  }
  if (!isObj(body) || body.queue === undefined) return body;
  return { ...body, queue: linkQueue(body.queue, ctx) };
}
