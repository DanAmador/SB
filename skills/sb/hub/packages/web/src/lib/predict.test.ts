import { describe, expect, it, vi } from "vitest";
import { createElement, type ReactNode } from "react";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Queue, QueueItem, State } from "@sb-hub/contract";
import { predictQueue } from "./predict.ts";
import { useWrites } from "./hub.ts";

const links = { ticket: null, map: null, board: null, report: null, log: null };
const ticket = (key: string, state: QueueItem["state"] = "queued", extra: object = {}): QueueItem =>
  ({ key, kind: "ticket", agent: null, state, note: "", commit: null, tries: 0, started: null, ended: null, links, ...extra });
const job = (key: string, state: QueueItem["state"] = "queued"): QueueItem =>
  ({ key, kind: "job", agent: null, state, note: "", commit: null, tries: 0, started: null, ended: null, links }) as unknown as QueueItem;
const queue = (items: QueueItem[], extra: Partial<Queue> = {}): Queue =>
  ({ version: 7, seeded: true, paused: false, agent: null, items, maps: ["p/a", "p/b"], ...extra });
const keys = (q: Queue | null): string[] => (q?.items ?? []).map((i) => `${i.key}:${i.state}`);

describe("the queue a write will most likely leave", () => {
  it("moves a queued ticket among the queued ones, leaving the rest in place", () => {
    const q = queue([ticket("p/a#1", "running"), ticket("p/a#2"), ticket("p/a#3"), ticket("p/b#1")]);
    expect(keys(predictQueue(q, "POST /api/queue/move", { key: "p/b#1", to: 0, version: 7 }))).toEqual([
      "p/a#1:running",
      "p/b#1:queued",
      "p/a#2:queued",
      "p/a#3:queued",
    ]);
    expect(predictQueue(q, "POST /api/queue/move", { key: "p/a#1", to: 0, version: 7 })).toBeNull();
  });

  it("unqueues what the selection leaves out and keeps the version the page sent", () => {
    const q = queue([ticket("p/a#2"), ticket("p/a#3"), ticket("p/b#1")]);
    const out = predictQueue(q, "POST /api/queue/set", { keys: ["p/b#1", "p/a#2"], version: 7 });
    expect(keys(out)).toEqual(["p/a#2:queued", "p/b#1:queued"]);
    expect(out?.version).toBe(7);
  });

  it("queues a new ticket last in its map, and a failed one afresh, never a running one twice", () => {
    const q = queue([ticket("p/a#9", "running"), ticket("p/a#2"), ticket("p/b#1"), ticket("p/a#5", "failed", { agent: "max" })]);
    const out = predictQueue(q, "POST /api/queue/set", { keys: ["p/a#2", "p/b#1", "p/a#4", "p/a#5", "p/a#9"], version: 7 });
    expect(keys(out)).toEqual(["p/a#9:running", "p/a#2:queued", "p/a#4:queued", "p/a#5:queued", "p/b#1:queued"]);
    expect(out?.items.find((i) => i.key === "p/a#5")?.agent).toBe("max");
  });

  it("moves a map and its queued tickets with it", () => {
    const q = queue([ticket("p/a#1"), ticket("p/a#2"), ticket("p/b#1")]);
    const out = predictQueue(q, "POST /api/queue/move_map", { map: "p/b", to: 0, version: 7 });
    expect(out?.maps).toEqual(["p/b", "p/a"]);
    expect(keys(out)).toEqual(["p/b#1:queued", "p/a#1:queued", "p/a#2:queued"]);
  });

  it("pauses, and a resume drops the reason it was paused", () => {
    const q = queue([], { paused: true, note: "paused: three failed" });
    const out = predictQueue(q, "POST /api/queue/pause", { paused: false });
    expect(out?.paused).toBe(false);
    expect(out).not.toHaveProperty("note");
  });

  it("removes a queued job only, and leaves to the hub what it alone knows", () => {
    const q = queue([job("j1"), job("j2", "running")]);
    expect(keys(predictQueue(q, "POST /api/queue/remove_job", { key: "j1", version: 7 }))).toEqual(["j2:running"]);
    expect(predictQueue(q, "POST /api/queue/remove_job", { key: "j2", version: 7 })).toBeNull();
    expect(predictQueue(q, "POST /api/queue/map", { map: "p/c", version: 7 })).toBeNull();
  });

  it("sets an item's account, and its model only before its first try", () => {
    const q = queue([ticket("p/a#1"), ticket("p/a#2", "queued", { tries: 1, model: "sonnet" })]);
    const a = predictQueue(q, "POST /api/queue/item_agent", { key: "p/a#1", name: "max", model: "opus" });
    expect(a?.items[0]).toMatchObject({ agent: "max", model: "opus" });
    const b = predictQueue(q, "POST /api/queue/item_agent", { key: "p/a#2", model: "opus" });
    expect(b?.items[1]).toMatchObject({ model: "sonnet" });
  });
});

describe("a queue write", () => {
  it("draws its guess before the hub answers, and puts the old queue back when the hub refuses", async () => {
    let answer: (r: Response) => void = () => undefined;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((res) => (answer = res))));
    const qc = new QueryClient();
    const q = queue([ticket("p/a#1")]);
    qc.setQueryData(["state"], { queue: q });
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children);
    const { result } = renderHook(() => useWrites(), { wrapper });

    const done = result.current.queue("POST /api/queue/pause", { paused: true }, "Paused.");
    await vi.waitFor(() => { expect(qc.getQueryData<State>(["state"])?.queue.paused).toBe(true); });
    answer(new Response(JSON.stringify({ error: "no" }), { status: 500 }));
    expect(await done).toEqual({ ok: false, words: "no" });
    expect(qc.getQueryData<State>(["state"])?.queue).toEqual(q);
    vi.unstubAllGlobals();
  });
});
