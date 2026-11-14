import { mkdirSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { obsidianUri, type LinkContext, type Links } from "@sb-hub/contract";
import { createApp } from "./app.ts";
import { phoneSetting, type Phone } from "./config.ts";
import { linkContext } from "./vault.ts";
import type { Forward, Reply } from "./upstream.ts";

const PORT = 8765;
const HOST = `127.0.0.1:${String(PORT)}`;
/** The real hub's answer, written by tests/test_contract_fixtures.py. */
const STATE = (JSON.parse(readFileSync(new URL("../../contract/fixtures/state.json", import.meta.url), "utf8")) as { body: { queue: { items: { key: string }[]; cleared?: object[] } } & Record<string, unknown> }).body;

function setup(reply: (f: Forward) => Reply, webDir = "/nonexistent", links: LinkContext = { exists: () => false, real: (p) => p, findTicket: () => null, runs: {} }, phone?: Phone) {
  const sent: Forward[] = [];
  const logged: string[] = [];
  const app = createApp({
    port: PORT,
    phone,
    webDir,
    links,
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
    // the same answer, each queue item with its links (all null here: nothing exists on this disk)
    const nothing = { ticket: null, map: null, board: null, report: null, log: null };
    const queue = STATE.queue as { items: object[]; cleared?: object[] };
    expect(await r.json()).toEqual({
      ...STATE,
      queue: { ...queue, items: queue.items.map((i) => ({ ...i, links: nothing })), ...(queue.cleared ? { cleared: queue.cleared.map((i) => ({ ...i, links: nothing })) } : {}) },
    });
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
    const app = createApp({ port: PORT, webDir: "/nonexistent", links: { exists: () => false, real: (p) => p, findTicket: () => null, runs: {} }, log: () => undefined, upstream: () => Promise.reject(new Error("down")) });
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

describe("obsidian links", () => {
  it("adds the links of the notes that exist to every ticket row and queue item", async () => {
    const vault = realpathSync(mkdtempSync(join(tmpdir(), "vault-")));
    const ctx = linkContext(vault);
    const effort = join(vault, "wayfinder", "repo", "one");
    const run = join(vault, "wayfinder", "repo", "runs", "2026-11-13-one");
    mkdirSync(join(effort, "issues", "done"), { recursive: true });
    mkdirSync(run, { recursive: true });
    writeFileSync(join(effort, "map.md"), "map");
    writeFileSync(join(effort, "issues", "done", "001 A, 'b'.md"), "t");
    writeFileSync(join(run, "1.md"), "report");
    writeFileSync(join(run, "1.log"), "log");
    writeFileSync(join(run, "board.md"), "board");
    const items = STATE.queue.items.map((i): object => (i.key === "repo/one#1" ? { ...i, run, log: join(run, "1.log"), map: "repo/one" } : i));
    const state = { ...STATE, queue: { ...STATE.queue, runs: { "repo/one": join(run, "board.md") }, items } };
    const { call } = setup(() => json(200, state), "/nonexistent", ctx);
    const body = (await (await call("/api/state")).json()) as { queue: { items: { key: string; links: Links }[] } };
    const one = body.queue.items.find((i) => i.key === "repo/one#1");
    expect(one?.links).toEqual({
      ticket: obsidianUri(join(effort, "issues", "done", "001 A, 'b'.md"), ctx.vault),
      map: obsidianUri(join(effort, "map.md"), ctx.vault),
      board: obsidianUri(join(run, "board.md"), ctx.vault),
      report: obsidianUri(join(run, "1.md"), ctx.vault),
      log: obsidianUri(join(run, "1.log"), ctx.vault),
    });
    expect(body.queue.items.find((i) => i.key === "repo/one#3")?.links.report).toBeNull();
  });
});

describe("the phone", () => {
  const SECRET = "a-long-secret-for-the-phone";
  const PHONE = "192.168.1.20";
  const PH = `${PHONE}:${String(PORT)}`;
  const on = () => setup(() => json(200, STATE), "/nonexistent", undefined, { address: PHONE, secret: SECRET });
  const cookieFrom = (r: Response): string => (r.headers.get("set-cookie") ?? "").split(";")[0] ?? "";

  it("is off by default: only 127.0.0.1 and localhost are named, the phone's address is refused", async () => {
    expect(phoneSetting({})).toBeUndefined();
    const { call } = setup(() => json(200, STATE));
    expect((await call("/api/state")).status).toBe(200);
    expect((await call("/api/state", {}, `localhost:${String(PORT)}`)).status).toBe(200);
    expect((await call(`/api/state?token=${SECRET}`, {}, PH)).status).toBe(403);
  });

  it("is read from SB_HUB_PHONE_ADDRESS and SB_HUB_PHONE_SECRET, and refuses a setting that would open the hub wider", () => {
    expect(phoneSetting({ SB_HUB_PHONE_ADDRESS: PHONE, SB_HUB_PHONE_SECRET: SECRET })).toEqual({ address: PHONE, secret: SECRET });
    expect(() => phoneSetting({ SB_HUB_PHONE_ADDRESS: PHONE })).toThrow(/SECRET/);
    expect(() => phoneSetting({ SB_HUB_PHONE_ADDRESS: PHONE, SB_HUB_PHONE_SECRET: "short" })).toThrow(/SECRET/);
    expect(() => phoneSetting({ SB_HUB_PHONE_ADDRESS: "0.0.0.0", SB_HUB_PHONE_SECRET: SECRET })).toThrow(/0\.0\.0\.0/);
    expect(() => phoneSetting({ SB_HUB_PHONE_ADDRESS: "my-mac.local", SB_HUB_PHONE_SECRET: SECRET })).toThrow(/IPv4/);
  });

  it("keeps 127.0.0.1 without a secret and refuses every other name, with the phone on", async () => {
    const { call } = on();
    expect((await call("/api/state")).status).toBe(200);
    expect((await call("/api/state", {}, `192.168.1.21:${String(PORT)}`)).status).toBe(403);
    expect((await call("/api/state", {}, "evil.example:8765")).status).toBe(403);
    expect((await call("/api/state", {}, PHONE)).status).toBe(403);
  });

  it("answers nothing to the phone's address without the secret, or with a wrong one", async () => {
    const { call, sent } = on();
    for (const path of ["/api/state", "/next/", "/", "/api/state?token=wrong"]) {
      const r = await call(path, {}, PH);
      expect([r.status, await r.text()]).toEqual([404, ""]);
    }
    const bad = await call("/api/state", { headers: { cookie: "sbhub=nope" } }, PH);
    expect(bad.status).toBe(404);
    expect(sent).toHaveLength(0);
  });

  it("takes the secret's link once: it sets a cookie, and the cookie opens the hub", async () => {
    const { call } = on();
    const first = await call(`/?token=${SECRET}`, {}, PH);
    expect([first.status, first.headers.get("location")]).toEqual([302, "/next/"]);
    const set = first.headers.get("set-cookie") ?? "";
    expect(set).toMatch(/HttpOnly/);
    expect(set).toMatch(/SameSite=Strict/);
    expect(set).not.toContain(SECRET);
    const state = await call("/api/state", { headers: { cookie: cookieFrom(first) } }, PH);
    expect(state.status).toBe(200);
  });

  it("answers a POST from the phone's own origin, with the cookie", async () => {
    const { call, sent } = on();
    const cookie = cookieFrom(await call(`/?token=${SECRET}`, {}, PH));
    const init = { method: "POST", body: "{}", headers: { cookie, "content-type": "application/json", origin: `http://${PH}` } };
    await call("/api/queue/pause", init, PH);
    expect(sent).toHaveLength(1);
    const other = await call("/api/queue/pause", { ...init, headers: { ...init.headers, origin: "http://evil.example" } }, PH);
    expect(other.status).toBe(403);
  });
});

describe("links by vault name", () => {
  it("name the vault and the note's path in it, not the Mac's path", async () => {
    const vault = realpathSync(mkdtempSync(join(tmpdir(), "My Vault-")));
    const effort = join(vault, "wayfinder", "repo", "one");
    mkdirSync(join(effort, "issues"), { recursive: true });
    writeFileSync(join(effort, "issues", "001 A.md"), "x");
    writeFileSync(join(effort, "map.md"), "x");
    const ctx = linkContext(vault);
    const name = encodeURIComponent(vault.split("/").pop() ?? "");
    expect(obsidianUri(join(effort, "map.md"), ctx.vault)).toBe(`obsidian://open?vault=${name}&file=wayfinder%2Frepo%2Fone%2Fmap.md`);
    const state = { ...STATE, queue: { ...STATE.queue, items: [{ ...STATE.queue.items[0], key: "repo/one#1", kind: "ticket" }] } };
    const { call } = setup(() => json(200, state), "/nonexistent", ctx);
    const body = (await (await call("/api/state")).json()) as { queue: { items: { links: Links }[] } };
    expect(body.queue.items[0]?.links.ticket).toBe(`obsidian://open?vault=${name}&file=wayfinder%2Frepo%2Fone%2Fissues%2F001%20A.md`);
    expect(JSON.stringify(body)).not.toContain(encodeURIComponent(vault));
  });
});
