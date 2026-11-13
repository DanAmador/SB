import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { createApp } from "./app.ts";
import type { Forward, Reply } from "./upstream.ts";

const PORT = 8765;
const HOST = `127.0.0.1:${String(PORT)}`;
/** The real hub's answer, written by tests/test_contract_fixtures.py. */
const STATE = (JSON.parse(readFileSync(new URL("../../contract/fixtures/state.json", import.meta.url), "utf8")) as { body: object }).body;

function setup(reply: (f: Forward) => Reply, webDir = "/nonexistent") {
  const sent: Forward[] = [];
  const logged: string[] = [];
  const app = createApp({
    port: PORT,
    webDir,
    log: (l) => logged.push(l),
    upstream: (f) => {
      sent.push(f);
      return Promise.resolve(reply(f));
    },
  });
  const call = (path: string, init: RequestInit = {}, host = HOST) =>
    app.request(`http://${host}${path}`, { ...init, headers: { host, ...(init.headers as Record<string, string> | undefined) } });
  return { call, sent, logged };
}

const json = (status: number, body: unknown, headers: Record<string, string> = {}): Reply => ({
  status,
  contentType: "application/json",
  body: Buffer.from(JSON.stringify(body)),
  headers,
});

describe("forwarding to the Python hub", () => {
  it("passes on an answer the contract allows, with the safety headers", async () => {
    const { call, sent } = setup(() => json(200, STATE));
    const r = await call("/api/state");
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual(STATE);
    expect(r.headers.get("x-frame-options")).toBe("DENY");
    expect(r.headers.get("x-content-type-options")).toBe("nosniff");
    expect(sent[0]?.path).toBe("/api/state");
  });

  it("logs a mismatch and answers 502 instead of passing it on", async () => {
    const { call, logged } = setup(() => json(200, { ...STATE, now: "soon" }));
    const r = await call("/api/state");
    expect(r.status).toBe(502);
    expect(await r.json()).toEqual({ ok: false, error: "the hub's answer to GET /api/state did not match the contract" });
    expect(logged).toHaveLength(1);
    expect(logged[0]).toContain("GET /api/state answered 200: now:");
  });

  it("checks the answer by its status: a lock held is a 409", async () => {
    const { call } = setup(() => json(409, { ok: false, held_by: "b" }));
    const r = await call("/api/lock", { method: "POST", body: '{"key":"k","by":"a"}', headers: { "content-type": "application/json" } });
    expect(r.status).toBe(409);
    expect(await r.json()).toEqual({ ok: false, held_by: "b" });
  });

  it("forwards a POST's body as sent, without the caller's Origin", async () => {
    const { call, sent } = setup(() => json(200, { ok: true, needs_you: false, agent: "a" }));
    const body = '{"agent":"a","state":"idle"}';
    const r = await call("/api/report", { method: "POST", body, headers: { "content-type": "application/json", origin: `http://${HOST}` } });
    expect(r.status).toBe(200);
    expect(sent[0]?.body?.toString()).toBe(body);
    expect(sent[0]?.headers).toEqual({ "content-type": "application/json" });
  });

  it("refuses a POST that is not JSON or comes from another origin, without asking the hub", async () => {
    const { call, sent } = setup(() => json(200, { ok: true }));
    const plain = await call("/api/report", { method: "POST", body: "{}", headers: { "content-type": "text/plain" } });
    const other = await call("/api/report", { method: "POST", body: "{}", headers: { "content-type": "application/json", origin: "http://evil.example" } });
    expect([plain.status, other.status]).toEqual([403, 403]);
    expect(sent).toHaveLength(0);
  });

  it("refuses a Host that does not name the hub", async () => {
    const { call, sent } = setup(() => json(200, STATE));
    const r = await call("/api/state", {}, "evil.example:8765");
    expect(r.status).toBe(403);
    expect(sent).toHaveLength(0);
  });

  it("passes a clip's byte range both ways", async () => {
    const { call, sent } = setup(() => ({
      status: 206,
      contentType: "video/mp4",
      body: Buffer.from("ab"),
      headers: { "accept-ranges": "bytes", "content-range": "bytes 0-1/10" },
    }));
    const r = await call("/api/media?key=k&name=a.mp4", { headers: { range: "bytes=0-1" } });
    expect(r.status).toBe(206);
    expect(r.headers.get("content-range")).toBe("bytes 0-1/10");
    expect(await r.text()).toBe("ab");
    expect(sent[0]?.headers).toEqual({ range: "bytes=0-1" });
  });

  it("checks a text answer as text", async () => {
    const { call } = setup(() => ({ status: 200, contentType: "text/plain; charset=utf-8", body: Buffer.from("# Report"), headers: {} }));
    const r = await call("/api/item/report?key=k");
    expect([r.status, await r.text()]).toEqual([200, "# Report"]);
  });

  it("passes on the hub's 404 for a route it does not have", async () => {
    const { call } = setup(() => json(404, { ok: false, error: "not found" }));
    expect((await call("/api/nope")).status).toBe(404);
  });

  it("says the hub is starting while the Python hub is not up", async () => {
    const app = createApp({ port: PORT, webDir: "/nonexistent", log: () => undefined, upstream: () => Promise.reject(new Error("down")) });
    const r = await app.request(`http://${HOST}/api/state`, { headers: { host: HOST } });
    expect(r.status).toBe(503);
  });
});

describe("pages", () => {
  it("serves the built board at /next/ and sends / there", async () => {
    const dir = mkdtempSync(join(tmpdir(), "web-"));
    writeFileSync(join(dir, "index.html"), "<!doctype html><title>sb hub</title>");
    mkdirSync(join(dir, "assets"));
    writeFileSync(join(dir, "assets", "app.js"), "export {};");
    const { call } = setup(() => json(200, STATE), dir);
    const home = await call("/");
    expect([home.status, home.headers.get("location")]).toEqual([302, "/next/"]);
    expect((await call("/next/assets/app.js")).status).toBe(200);
    const r = await call("/next/");
    expect(r.status).toBe(200);
    expect(r.headers.get("content-type")).toContain("text/html");
    expect(r.headers.get("x-frame-options")).toBe("DENY");
    expect(await r.text()).toContain("<title>sb hub</title>");
  });

  it("says how to build the board when it is not built", async () => {
    const { call } = setup(() => json(200, STATE));
    const r = await call("/");
    expect(r.status).toBe(503);
    expect(await r.text()).toContain("pnpm --dir skills/sb/hub build");
  });

  it("serves the Python hub's own board at /classic, unchecked", async () => {
    const { call, sent } = setup(() => ({ status: 200, contentType: "text/html; charset=utf-8", body: Buffer.from("<html>"), headers: {} }));
    const r = await call("/classic");
    expect([r.status, await r.text(), sent[0]?.path]).toEqual([200, "<html>", "/"]);
  });

  it("answers 404 for any other path", async () => {
    const { call } = setup(() => json(200, STATE));
    expect((await call("/nope")).status).toBe(404);
  });
});
