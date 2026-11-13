/** The hub on its public port: the built board, and every /api route forwarded to the Python hub and checked. */
import { serveStatic } from "@hono/node-server/serve-static";
import { Hono, type Context } from "hono";
import { checkAnswer, type Verdict } from "./check.ts";
import type { Reply, Upstream } from "./upstream.ts";

export interface AppOptions {
  /** The port this server listens on: Host and Origin must name it. */
  readonly port: number;
  readonly upstream: Upstream;
  /** packages/web/dist. */
  readonly webDir: string;
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

export function createApp(o: AppOptions): Hono {
  const hosts = new Set([`127.0.0.1:${String(o.port)}`, `localhost:${String(o.port)}`]);
  const origins = new Set([...hosts].map((h) => `http://${h}`));
  const app = new Hono();

  // A page that rebinds its own name to 127.0.0.1 gets nothing, as with the Python hub; no answer may be framed or sniffed.
  app.use("*", async (c, next) => {
    if (!hosts.has(c.req.header("host") ?? "")) return error(403, "forbidden");
    await next();
    for (const [k, v] of Object.entries(SAFETY)) c.res.headers.set(k, v);
    return undefined;
  });

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
      const v: Verdict = checkAnswer(c.req.method, path, reply);
      if (!v.ok) {
        o.log(`contract mismatch: ${v.route} answered ${String(reply.status)}: ${v.problem}`);
        return error(502, `the hub's answer to ${v.route} did not match the contract`);
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

  // The Python hub's own board, until the new board replaces it.
  app.get("/classic", (c) => forward(c, "/", undefined, false));
  app.get("/board.js", (c) => forward(c, "/board.js", undefined, false));

  app.use("/*", serveStatic({ root: o.webDir, index: "index.html" }));
  app.get("/", () => answer(503, "The board is not built yet: run pnpm --dir skills/sb/hub build.\n", "text/plain; charset=utf-8"));
  app.all("*", () => error(404, "not found"));
  return app;
}
