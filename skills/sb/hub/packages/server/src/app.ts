/** The hub on its public port: the built board, and every /api route forwarded to the Python hub and checked. */
import { createHash, timingSafeEqual } from "node:crypto";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { serveStatic } from "@hono/node-server/serve-static";
import { addLinks, routeOf, type LinkContext } from "@sb-hub/contract";
import { Hono, type Context } from "hono";
import type { Phone } from "./config.ts";
import { checkAnswer, type Verdict } from "./check.ts";
import type { Reply, Upstream } from "./upstream.ts";

export interface AppOptions {
  /** The port this server listens on: Host and Origin must name it. */
  readonly port: number;
  readonly upstream: Upstream;
  /** packages/web/dist. */
  readonly webDir: string;
  /** The vault, for the obsidian:// links added to ticket rows and queue items. */
  readonly links: LinkContext;
  /** The extra address and its secret; absent, the hub answers only 127.0.0.1 and localhost. */
  readonly phone?: Phone | undefined;
  /** Where a mismatch with the contract is written. */
  readonly log: (line: string) => void;
}

const SAFETY = { "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff" } as const;

function answer(status: number, body: Buffer | string, contentType: string, extra: Readonly<Record<string, string>> = {}): Response {
  const bytes = typeof body === "string" ? Buffer.from(body) : body;
  // 204 and 304 carry no body; the hub never answers them, so every answer here has one.
  return new Response(new Uint8Array(bytes), { status, headers: { "Content-Type": contentType, ...extra, ...SAFETY } });
}

const error = (status: number, text: string): Response =>
  answer(status, JSON.stringify({ ok: false, error: text }), "application/json");

const COOKIE = "sbhub";
const digest = (s: string): Buffer => createHash("sha256").update(s).digest();
const same = (a: string, b: string): boolean => timingSafeEqual(digest(a), digest(b));

function cookieOf(header: string | undefined, name: string): string | undefined {
  for (const part of (header ?? "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
  }
  return undefined;
}

export function createApp(o: AppOptions): Hono {
  const local = [`127.0.0.1:${String(o.port)}`, `localhost:${String(o.port)}`];
  const phoneHost = o.phone === undefined ? undefined : `${o.phone.address}:${String(o.port)}`;
  const hosts = new Set(phoneHost === undefined ? local : [...local, phoneHost]);
  const origins = new Set([...hosts].map((h) => `http://${h}`));
  const app = new Hono();
  // What the phone's cookie must hold: a hash of the secret, so the secret itself is not kept on the phone.
  const proof = o.phone === undefined ? "" : digest(o.phone.secret).toString("hex");

  // A page that rebinds its own name to 127.0.0.1 gets nothing, as with the Python hub; no answer may be framed or sniffed.
  app.use("*", async (c, next) => {
    const host = c.req.header("host") ?? "";
    if (!hosts.has(host)) return error(403, "forbidden");
    if (host === phoneHost && o.phone !== undefined) {
      // From off the Mac: the secret's link sets the cookie once; without the cookie the hub answers nothing at all.
      const given = c.req.query("token");
      if (given !== undefined && same(given, o.phone.secret)) {
        const u = new URL(c.req.url);
        u.searchParams.delete("token");
        const to = u.pathname === "/" ? "/next/" : u.pathname + u.search;
        return new Response(null, { status: 302, headers: { Location: to, "Set-Cookie": `${COOKIE}=${proof}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000`, "Cache-Control": "no-store", ...SAFETY } });
      }
      if (!same(cookieOf(c.req.header("cookie"), COOKIE) ?? "", proof)) return new Response(null, { status: 404, headers: SAFETY });
    }
    await next();
    for (const [k, v] of Object.entries(SAFETY)) c.res.headers.set(k, v);
    return undefined;
  });

  /** The reply with `links` added to its ticket rows and queue items; an answer that is not JSON is left to the check. */
  function withLinks(method: string, path: string, reply: Reply): Reply {
    const route = routeOf(method, path);
    if (route === undefined || !reply.contentType.startsWith("application/json")) return reply;
    try {
      const body = addLinks(route, JSON.parse(reply.body.toString("utf8")) as unknown, o.links);
      return { ...reply, body: Buffer.from(JSON.stringify(body)) };
    } catch {
      return reply;
    }
  }

  const unknownSeen = new Set<string>();

  /** The Python hub's answer to `path` (path and query), passed on only when the contract allows it. */
  async function forward(c: Context, path: string, body?: Buffer, check = true): Promise<Response> {
    const headers: Record<string, string> = {};
    const range = c.req.header("range");
    if (range !== undefined) headers.range = range;
    if (body !== undefined) headers["content-type"] = "application/json";
    let reply: Reply;
    try {
      reply = await o.upstream({ method: c.req.method, path, headers, ...(body === undefined ? {} : { body }) });
    } catch {
      return error(503, "the hub is starting or its Python half is down");
    }
    if (check) {
      reply = withLinks(c.req.method, path, reply);
      const v: Verdict = checkAnswer(c.req.method, path, reply);
      if (!v.ok) {
        o.log(`contract mismatch: ${v.route} answered ${String(reply.status)}: ${v.problem}`);
        return error(502, `the hub's answer to ${v.route} did not match the contract`);
      }
      if (v.unknown !== undefined) {
        // a key the contract does not know is dropped, and named once per route, not on every poll
        for (const k of v.unknown) {
          const seen = `${c.req.method} ${path.split("?", 1)[0] ?? ""} ${k}`;
          if (!unknownSeen.has(seen)) {
            unknownSeen.add(seen);
            o.log(`unknown key dropped: ${seen}`);
          }
        }
        reply = { ...reply, body: Buffer.from(JSON.stringify(v.value)) };
      }
    }
    return answer(reply.status, reply.body, reply.contentType, reply.headers);
  }

  const asked = (c: Context): string => {
    const u = new URL(c.req.url);
    return u.pathname + u.search;
  };

  app.get("/api/*", (c) => forward(c, asked(c)));
  app.post("/api/*", async (c) => {
    // A POST must be JSON and not from another origin: a web page cannot post to the hub.
    const ctype = (c.req.header("content-type")?.split(";", 1)[0] ?? "").trim().toLowerCase();
    const origin = c.req.header("origin");
    if (ctype !== "application/json" || (origin !== undefined && !origins.has(origin))) return error(403, "forbidden");
    return forward(c, asked(c), Buffer.from(await c.req.arrayBuffer()));
  });

  // The board is built for /next/ (Vite's base), so it lives there; / sends you to it once it is built.
  app.get("/next", (c) => c.redirect("/next/"));
  app.use("/next/*", serveStatic({ root: o.webDir, index: "index.html", rewriteRequestPath: (p) => p.replace(/^\/next/, "") }));
  app.get("/", (c) => existsSync(join(o.webDir, "index.html")) ? c.redirect("/next/")
    : answer(503, "The board is not built yet: run pnpm --dir skills/sb/hub build.\n", "text/plain; charset=utf-8"));
  app.all("*", () => error(404, "not found"));
  return app;
}
