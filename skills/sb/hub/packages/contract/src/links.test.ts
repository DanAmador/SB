/** The links the API carries are the links `sbmap uri` prints for the same files. */
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { Links, addLinks, itemLinks, mapNote, obsidianUri, rowLinks, type LinkContext } from "./index.ts";

const SBMAP = join(import.meta.dirname, "..", "..", "..", "..", "scripts", "sbmap.py");
const vault = realpathSync(mkdtempSync(join(tmpdir(), "vault-")));

/** What `sbmap uri <file>` prints between the parentheses. */
function sbmapUri(file: string): string {
  const out = execFileSync("python3", [SBMAP, "uri", file], { env: { ...process.env, SB_VAULT: vault }, encoding: "utf8" }).trim();
  return out.slice(out.lastIndexOf("](") + 2, -1);
}

const note = (rel: string): string => {
  const f = join(vault, rel);
  mkdirSync(join(f, ".."), { recursive: true });
  writeFileSync(f, "---\ntitle: T\n---\nbody\n");
  return f;
};

const NAMES = [
  "wayfinder/repo/one/issues/039 Every ticket, report and log opens in Obsidian.md",
  "wayfinder/repo/one/issues/done/001 It's (done)! *really* ~ #1 & 100% [x].md",
  "wayfinder/repo/one/issues/002 Café für Zoë – “quotes” 日本.md",
  "wayfinder/repo/one/map.md",
  "wayfinder/repo/runs/2026-11-13-one/1.md",
];

describe("obsidianUri", () => {
  it.each(NAMES)("matches sbmap uri for %s", (rel) => {
    const f = note(rel);
    expect(obsidianUri(f)).toBe(sbmapUri(f));
  });
});

describe("links", () => {
  const ticket = note(NAMES[0] ?? "");
  const map = note("wayfinder/repo/one/map.md");
  const run = join(vault, "wayfinder", "repo", "runs", "2026-11-13-one");
  const board = note("wayfinder/repo/runs/2026-11-13-one/board.md");
  const report = note("wayfinder/repo/runs/2026-11-13-one/39.md");
  const log = join(run, "39.log");
  writeFileSync(log, "log");
  const ctx = (): LinkContext => ({
    real: realpathSync,
    exists: (p) => p.startsWith(vault) && (p === ticket || p === map || p === board || p === report || p === log),
    findTicket: (m, n) => (m === "repo/one" && n === 39 ? ticket : null),
    runs: { "repo/one": board },
  });

  it("an item links its ticket, map, run board, report and log as sbmap uri does", () => {
    const l = itemLinks({ key: "repo/one#39", kind: "ticket", run, log }, ctx());
    expect(l).toEqual({ ticket: sbmapUri(ticket), map: sbmapUri(map), board: sbmapUri(board), report: sbmapUri(report), log: sbmapUri(log) });
    expect(Links.safeParse(l).success).toBe(true);
  });

  it("a note that is not there is null, not a dead link", () => {
    const l = itemLinks({ key: "repo/one#40", kind: "ticket", run, log: join(run, "40.log") }, ctx());
    expect(l).toEqual({ ticket: null, map: null, board: sbmapUri(board), report: null, log: null });
  });

  it("a job links its result and log only", () => {
    expect(itemLinks({ key: "job-1", kind: "job", result: report, log }, ctx())).toEqual({ ticket: null, map: null, board: null, report: sbmapUri(report), log: sbmapUri(log) });
  });

  it("a ticket row links its note, map and board", () => {
    expect(rowLinks({ map: "repo/one", file: ticket }, ctx())).toEqual({ ticket: sbmapUri(ticket), map: sbmapUri(map), board: sbmapUri(board), report: null, log: null });
  });

  it("finds a ticket's map from a done ticket's path", () => {
    expect(mapNote("/v/wayfinder/r/e/issues/done/001 A.md")).toBe("/v/wayfinder/r/e/map.md");
    expect(mapNote("/v/other.md")).toBeNull();
  });

  it("addLinks adds links to every item of a queue and every ticket row, and learns the boards", () => {
    const c = ctx();
    c.runs = {};
    const q = { runs: { "repo/one": board }, items: [{ key: "repo/one#39", kind: "ticket", run, log }], cleared: [{ key: "x", kind: "job" }] };
    const out = addLinks("POST /api/queue/pause", { ok: true, queue: q }, c) as { queue: { items: { links: unknown }[]; cleared: { links: unknown }[] } };
    expect(out.queue.items[0]?.links).toMatchObject({ report: sbmapUri(report) });
    expect(out.queue.cleared[0]?.links).toEqual({ ticket: null, map: null, board: null, report: null, log: null });
    const rows = addLinks("GET /api/tickets", [{ map: "repo/one", file: ticket }], c) as { links: { board: string } }[];
    expect(rows[0]?.links.board).toBe(sbmapUri(board));
  });
});
