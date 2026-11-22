import { describe, expect, it, vi } from "vitest";
import { createElement, type ReactNode } from "react";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { MapRoute, TicketDetail, TicketRow } from "@sb-hub/contract";
import { classify, guessTicket } from "./ticketGuess.ts";
import { useWrites } from "./hub.ts";

const links = { ticket: null, map: null, board: null, report: null, log: null };
const row = (num: number, extra: Partial<TicketRow> = {}): TicketRow =>
  ({
    map: "p/a", num, title: `T${String(num)}`, why: "", type: "task", status: "open", priority: null, blocked_by: [], blocked_by_open: [],
    paths: [], tier: "sonnet", check: "tests", has_done_when: true, done_when: "x", question: "", out: "", checks: [], repo: "/r",
    file: "", map_title: "A", map_order: 0, claimed_by: null, queued: false, state: "ready", reason: "ready", links, ...extra,
  });
const route = (): MapRoute =>
  ({
    map: "p/a", title: "A", status: "open", words: "", checks: [], uri: "",
    tickets: [1, 2].map((num) => ({ num, title: "", type: "task", status: "open", state: "ready", why: "", priority: null, tier: "sonnet", place: 1, last_run: null, blocked_by: [], file: "", links })),
  });
const apply = (g: ReturnType<typeof guessTicket>, rows: TicketRow[]): TicketRow[] => g?.tickets?.(rows) ?? rows;

describe("what a ticket action will most likely change", () => {
  it("Done and Drop take the row off the open list and finish it on its map", () => {
    const g = guessTicket("done", { key: "p/a#1", text: "shipped" });
    expect(apply(g, [row(1), row(2)]).map((r) => r.num)).toEqual([2]);
    expect(g?.route?.(route()).tickets[0]).toMatchObject({ status: "resolved", state: "done", place: null });
    expect(g?.detail?.({ open: true } as TicketDetail).open).toBe(false);
    const d = guessTicket("drop", { key: "p/a#2", text: "no" });
    expect(d?.route?.(route()).tickets[1]).toMatchObject({ status: "out-of-scope", state: "out of scope" });
  });

  it("Release opens a claimed ticket and says its state again", () => {
    const g = guessTicket("release", { key: "p/a#1" });
    const [r] = apply(g, [row(1, { status: "claimed", claimed_by: "s1", state: "claimed" })]);
    expect(r).toMatchObject({ status: "open", claimed_by: null, state: "ready" });
  });

  it("a ruled decision is no longer waiting for you", () => {
    const g = guessTicket("rule", { key: "p/a#1", text: "  option  two " });
    const [r] = apply(g, [row(1, { type: "grilling", state: "waits for you" })]);
    expect(r).toMatchObject({ ruling: "option two", state: "not ready" });
  });

  it("an empty Done when makes it not ready; Files are one per line", () => {
    expect(apply(guessTicket("done_when", { key: "p/a#1", text: "  " }), [row(1)])[0]).toMatchObject({ has_done_when: false, state: "not ready" });
    expect(apply(guessTicket("paths", { key: "p/a#1", text: "a.ts\n\n b.ts " }), [row(1)])[0]?.paths).toEqual(["a.ts", "b.ts"]);
  });

  it("map checks reach the map and every ticket of it with none of its own", () => {
    const g = guessTicket("checks", { key: "p/a#1", text: "pnpm test; pnpm lint" });
    const rows = apply(g, [row(1), row(2, { checks: ["own"], checks_from: "ticket" }), row(3, { map: "p/b" })]);
    expect(rows.map((r) => r.checks)).toEqual([["pnpm test", "pnpm lint"], ["own"], []]);
    expect(g?.route?.(route()).checks).toEqual(["pnpm test", "pnpm lint"]);
  });

  it("a blocked ticket waits on an open blocker that is not queued", () => {
    const first = row(1, { blocked_by_open: [2] });
    expect(classify(first, [first, row(2)])).toEqual({ state: "blocked", reason: "after T2" });
    expect(classify(first, [first, row(2, { queued: true })]).state).toBe("ready");
  });

  it("draws nothing for a comment", () => {
    expect(guessTicket("comment", { key: "p/a#1", text: "hi" })).toBeNull();
  });
});

describe("a ticket action", () => {
  it("draws its guess before the hub answers, sends actions one at a time, and undoes a refused one", async () => {
    const answers: ((r: Response) => void)[] = [];
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((res) => answers.push(res))));
    const qc = new QueryClient();
    const rows = [row(1), row(2)];
    qc.setQueryData(["tickets"], rows);
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children);
    const { result } = renderHook(() => useWrites(), { wrapper });

    const one = result.current.ticket("done", { key: "p/a#1", text: "ok" }, "Done.");
    const two = result.current.ticket("tier", { key: "p/a#2", text: "opus" }, "Tier.");
    await vi.waitFor(() => { expect(qc.getQueryData<TicketRow[]>(["tickets"])?.map((r) => `${String(r.num)}:${r.tier}`)).toEqual(["2:opus"]); });
    expect(answers).toHaveLength(1); // the second waits for the first
    answers[0]?.(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    expect(await one).toEqual({ ok: true, words: "Done." });
    await vi.waitFor(() => { expect(answers).toHaveLength(2); });
    answers[1]?.(new Response(JSON.stringify({ error: "a worker is running it" }), { status: 400 }));
    expect(await two).toEqual({ ok: false, words: "a worker is running it" });
    vi.unstubAllGlobals();
  });

  it("puts the list back when the hub refuses and nothing else is on its way", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ error: "no such ticket" }), { status: 400 }))));
    const qc = new QueryClient();
    const rows = [row(1), row(2)];
    qc.setQueryData(["tickets"], rows);
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children);
    const { result } = renderHook(() => useWrites(), { wrapper });
    expect(await result.current.ticket("drop", { key: "p/a#1", text: "no" }, "Dropped.")).toEqual({ ok: false, words: "no such ticket" });
    expect(qc.getQueryData<TicketRow[]>(["tickets"])?.map((r) => r.num)).toEqual([1, 2]);
    vi.unstubAllGlobals();
  });
});
