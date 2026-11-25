import { describe, expect, it } from "vitest";
import type { FeedEvent } from "@sb-hub/contract";
import { quickSteers } from "@/components/LiveFeed.tsx";
import { headlineOf, rowsOf } from "./feed.ts";

const events: FeedEvent[] = [
  { k: "start", model: "claude-sonnet-5-5" },
  { k: "say", text: "Reading the ticket.\nThen the code." },
  { k: "tool", id: "a", name: "Bash", arg: "grep -n foo" },
  { k: "tool", id: "b", name: "Edit", arg: "/x.ts" },
  { k: "result", id: "b", ok: false, text: "no match" },
  { k: "result", id: "zz", ok: true, text: "a result whose call fell off the top" },
  { k: "owner", text: "Wrap up now." },
];

describe("the live feed's rows", () => {
  it("joins each result to its call and keeps the rest in order", () => {
    expect(rowsOf(events)).toEqual([
      { k: "start", model: "claude-sonnet-5-5" },
      { k: "say", text: "Reading the ticket.\nThen the code." },
      { k: "tool", name: "Bash", arg: "grep -n foo", result: null },
      { k: "tool", name: "Edit", arg: "/x.ts", result: { ok: false, text: "no match" } },
      { k: "owner", text: "Wrap up now." },
    ]);
  });

  it("heads the feed with the worker's last sentence, its first line", () => {
    expect(headlineOf(events)).toBe("Reading the ticket.");
    expect(headlineOf([{ k: "tool", id: "a", name: "Bash", arg: "ls" }])).toBeNull();
  });

  it("offers Stay in its files only when the ticket names files", () => {
    expect(quickSteers([]).map(([l]) => l)).toEqual(["Where are you?", "Wrap up now"]);
    expect(quickSteers(["a.ts", "b.ts"]).at(-1)?.[1]).toContain("a.ts, b.ts");
  });
});
