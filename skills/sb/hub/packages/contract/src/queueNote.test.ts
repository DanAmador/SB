/**
 * A queue the hub paused by itself carries a note saying why. On 2026-11-16 that note was missing from the
 * contract, so every GET /api/state failed and the page showed the hub as down all morning.
 */
import { describe, expect, it } from "vitest";
import { Queue } from "./index.ts";

// The real hub's queue of 2026-11-16 08:30, its lists emptied.
const paused = {
  version: 2901,
  seeded: true,
  paused: true,
  agent: "personal",
  agents: ["personal", "assembio"],
  close_off_day: "2026-11-16",
  stop_at: null,
  final_review: true,
  maps: ["sk4te/party-playtest", "sk4te/builds-that-work", "sk4te/cutaway", "sk4te/chase"],
  night: "night-20261115-152229",
  note: "paused: three tickets in a row failed with the check python3 .sb/checks-compile.py",
  items: [],
};

describe("a queue the hub paused by itself", () => {
  it("parses with its note", () => {
    expect(Queue.parse(paused).note).toBe(paused.note);
  });
  it("parses with no note", () => {
    const { note: _, ...plain } = paused;
    expect(Queue.parse(plain).note).toBeUndefined();
  });
});
