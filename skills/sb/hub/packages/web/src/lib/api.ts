/**
 * The typed client: every call names a contract route, sends the body that route takes and parses the answer with
 * the route's own schema, so a field the hub renames fails here, loudly, instead of drawing nothing.
 */
import { ROUTES, answerSchema, type RouteAnswer, type RouteBody, type RouteName } from "@sb-hub/contract";

/** The hub's paths are absolute: the page lives under /next/, the API under /api/. */
const BASE = "";

export class HubError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "HubError";
  }
}

type GetRoute = Extract<RouteName, `GET ${string}`>;
type PostRoute = Extract<RouteName, `POST ${string}`>;
type JsonGet = { [K in GetRoute]: (typeof ROUTES)[K]["kind"] extends "json" ? K : never }[GetRoute];

const pathOf = (route: RouteName): string => route.slice(route.indexOf(" ") + 1);

function parse(route: RouteName, status: number, body: unknown): unknown {
  const schema = answerSchema(route, status);
  if (schema === undefined) throw new HubError(`the hub said ${String(status)}`, status);
  const out = schema.safeParse(body);
  if (!out.success) throw new HubError(`the hub's answer to ${route} does not match the contract`, status);
  return out.data;
}

async function errorOf(r: Response): Promise<HubError> {
  const body: unknown = await r.json().catch(() => null);
  const said = typeof body === "object" && body !== null && "error" in body && typeof body.error === "string" ? body.error : null;
  return new HubError(said ?? `the hub said ${String(r.status)}`, r.status);
}

/** A JSON GET, with its query string. */
export async function get<K extends JsonGet>(route: K, query?: Record<string, string>): Promise<RouteAnswer<K>> {
  const qs = query ? `?${new URLSearchParams(query).toString()}` : "";
  const r = await fetch(`${BASE}${pathOf(route)}${qs}`, { cache: "no-store" });
  if (!r.ok) throw await errorOf(r);
  return parse(route, r.status, await r.json()) as RouteAnswer<K>;
}

/** A plain-text GET: a worker's report or log. */
export async function getText(route: "GET /api/item/report" | "GET /api/item/log", key: string): Promise<string> {
  const r = await fetch(`${BASE}${pathOf(route)}?key=${encodeURIComponent(key)}`, { cache: "no-store" });
  if (!r.ok) throw await errorOf(r);
  return r.text();
}

/** What a POST answered: its 200 body, or the other answer the route lists for a status it gives (a stale 409). */
export type PostResult<K extends PostRoute> =
  | { ok: true; data: RouteAnswer<K> }
  | { ok: false; status: number; data: unknown; error: string };

export async function post<K extends PostRoute>(route: K, body: RouteBody<K>, path?: string): Promise<PostResult<K>> {
  const url = `${BASE}${path ?? pathOf(route)}`;
  const init = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(url, init).catch(() => null);
  if (r === null) return { ok: false, status: 0, data: null, error: "hub not reachable" };
  const raw: unknown = await r.json().catch(() => null);
  if (r.ok) return { ok: true, data: parse(route, r.status, raw) as RouteAnswer<K> };
  const known = answerSchema(route, r.status)?.safeParse(raw);
  const data = known?.success === true ? known.data : raw;
  const said = typeof data === "object" && data !== null && "error" in data && typeof data.error === "string" ? data.error : null;
  return { ok: false, status: r.status, data, error: said ?? `the hub said ${String(r.status)}` };
}

/** A ticket action's path: POST /api/ticket/done and so on. */
export const ticketPath = (action: string): string => `/api/ticket/${action}`;

export const mediaUrl = (key: string, name: string): string =>
  `${BASE}/api/media?key=${encodeURIComponent(key)}&name=${encodeURIComponent(name)}`;
export const itemUrl = (what: "report" | "log", key: string): string =>
  `${BASE}/api/item/${what}?key=${encodeURIComponent(key)}`;
