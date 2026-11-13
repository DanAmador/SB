/**
 * Every answer the Python hub gave in tests/test_contract_fixtures.py parses with its route's schema. A field
 * renamed in sbhub.py shows up in the regenerated fixture as an unknown or missing key and fails here.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import { ApiError, ROUTES, RepoProvider, State, answerSchema, bodySchema, routeOf, type RouteAnswer, type RouteName } from "./index.ts";

const Fixture = z.strictObject({
  route: z.string().regex(/^(GET|POST) \/api\//),
  status: z.number().int(),
  contentType: z.string(),
  request: z.unknown().optional(),
  body: z.unknown().optional(),
  bytes: z.number().int().optional(),
});
type Fixture = z.infer<typeof Fixture>;

const dir = join(import.meta.dirname, "..", "fixtures");
const fixtures = readdirSync(dir)
  .filter((f) => f.endsWith(".json"))
  .sort()
  .map((f): [string, Fixture] => [f, Fixture.parse(JSON.parse(readFileSync(join(dir, f), "utf8")))]);

function routeFor(fx: Fixture): RouteName | undefined {
  const [method = "", path = ""] = fx.route.split(" ");
  return routeOf(method, path);
}

describe("fixtures written by the hub", () => {
  it("were written (run python3 -m unittest discover tests)", () => {
    expect(fixtures.length).toBeGreaterThan(40);
  });

  it.each(fixtures)("%s parses with its route's schema", (_, fx) => {
    const route = routeFor(fx);
    if (route === undefined) {
      // a path the hub does not serve: a JSON 404
      expect(fx.status).toBe(404);
      ApiError.parse(fx.body);
      return;
    }
    const schema = answerSchema(route, fx.status);
    expect(schema, `${fx.route} never answers ${String(fx.status)}`).toBeDefined();
    const kind = ROUTES[route].kind;
    if (kind === "media") {
      schema?.parse(fx.status === 200 || fx.status === 206 ? fx.contentType : "");
    } else {
      expect(fx.contentType).toBe(kind === "text" && fx.status === 200 ? "text/plain; charset=utf-8" : "application/json");
      schema?.parse(fx.body);
    }
    const body = bodySchema(route);
    if (body !== undefined) {
      // a body the hub refused with a 400 is one the contract refuses too
      expect(body.safeParse(fx.request).success, "the request body").toBe(fx.status !== 400);
    }
  });

  it("covers every route and the queue's stale answer", () => {
    const seen = new Set(fixtures.map(([, fx]) => `${routeFor(fx) ?? fx.route} ${String(fx.status)}`));
    for (const route of Object.keys(ROUTES) as RouteName[]) {
      expect([...seen].some((k) => k.startsWith(`${route} `)), route).toBe(true);
    }
    expect(seen).toContain("POST /api/queue/set 409");
    expect(seen).toContain("POST /api/lock 409");
  });

  it("holds the hub's own provider panel to its exact shape", () => {
    const state = State.parse(fixtures.find(([f]) => f === "state.json")?.[1].body);
    const panels = Object.values(state.providers).flat();
    expect(panels.length).toBeGreaterThan(0);
    for (const p of panels) RepoProvider.parse(p);
  });
});

describe("the schemas refuse what the hub never sends", () => {
  const state = fixtures.find(([f]) => f === "state.json")?.[1].body as Record<string, unknown>;

  it("a renamed field", () => {
    const { now, ...rest } = state;
    expect(State.safeParse({ ...rest, time: now }).success).toBe(false);
  });

  it("an unknown route", () => {
    expect(routeOf("GET", "/api/nothing")).toBeUndefined();
    expect(routeOf("POST", "/api/ticket/delete")).toBeUndefined();
    expect(routeOf("GET", "/api/question/ab12?x=1")).toBe("GET /api/question/:id");
  });

  it("types follow the routes", () => {
    const stale: RouteAnswer<"POST /api/queue/set", 409> = { ok: false, stale: true, queue: State.parse(state).queue };
    expect(stale.stale).toBe(true);
  });
});
