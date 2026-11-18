import { readFileSync } from "node:fs";
import { join } from "node:path";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { addLinks } from "@sb-hub/contract";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setLink } from "@/lib/link.ts";
import { Board } from "./Board.tsx";

const NEXT = 1794528060 + 600;
/** The contract's state fixture with `landed` of its queued tickets finished and not yet reviewed. */
const stateWith = (landed: number): unknown => {
  const fx = JSON.parse(readFileSync(join(import.meta.dirname, "../../../contract/fixtures/state.json"), "utf8")) as { route: string; body: { queue: { items: { kind: string; state: string }[] }; review_next_at: number | null } };
  let n = 0;
  for (const i of fx.body.queue.items) if (i.kind === "ticket" && n < landed && ++n) i.state = "landed";
  fx.body.review_next_at = landed > 0 ? NEXT : null;
  return addLinks(fx.route as "GET /api/state", fx.body, { exists: () => false, real: (p) => p, findTicket: () => null, runs: {} });
};
const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const fixture = (name: string): unknown => (JSON.parse(readFileSync(join(import.meta.dirname, "../../../contract/fixtures", name), "utf8")) as { body: unknown }).body;

beforeEach(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: () => undefined, removeEventListener: () => undefined }));
  vi.stubGlobal("ResizeObserver", class { observe(): void { /* nothing */ } unobserve(): void { /* nothing */ } disconnect(): void { /* nothing */ } });
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const app = (landed: number, posts: string[] = []): void => {
  vi.stubGlobal("fetch", vi.fn((input: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      posts.push(input);
      return Promise.resolve(json({ ...(fixture("review-now.json") as object), started: ["repo/one", "repo/two"] }));
    }
    return Promise.resolve(input.startsWith("/api/state") ? json(stateWith(landed)) : json({ ok: false }, 404));
  }));
  // the button sits in Run's Maps tab
  setLink({ rt: "maps" });
  render(<QueryClientProvider client={new QueryClient()}><Board /></QueryClientProvider>);
};

describe("the Review finished now button", () => {
  it("counts the finished, unreviewed tickets and names the next timed look", async () => {
    app(2);
    const b = await screen.findByRole("button", { name: "Review 2 finished now" });
    expect((b as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText(/The next timed look is at/)).not.toBeNull();
  });

  it("is off when nothing waits", async () => {
    app(0);
    const b = await screen.findByRole("button", { name: "Review finished now" });
    expect((b as HTMLButtonElement).disabled).toBe(true);
  });

  it("posts to /api/review/now and shows the maps it started", async () => {
    const posts: string[] = [];
    app(2, posts);
    fireEvent.click(await screen.findByRole("button", { name: "Review 2 finished now" }));
    await screen.findByText("Review started on repo/one, repo/two.");
    expect(posts).toEqual(["/api/review/now"]);
  });
});
