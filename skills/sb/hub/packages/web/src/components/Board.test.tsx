import { readFileSync } from "node:fs";
import { join } from "node:path";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { addLinks } from "@sb-hub/contract";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Board } from "./Board.tsx";

/** The state the hub itself wrote in its contract test (packages/contract/fixtures), with the TypeScript server's links added. */
const real = (name: string): unknown => {
  const fx = JSON.parse(readFileSync(join(import.meta.dirname, "../../../contract/fixtures", name), "utf8")) as { route: string; body: unknown };
  return addLinks(fx.route as "GET /api/state", fx.body, { exists: () => false, real: (p) => p, findTicket: () => null, runs: {} });
};
const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  // jsdom has neither; the board reads the window's width and watches its own size
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: () => undefined, removeEventListener: () => undefined }));
  vi.stubGlobal("ResizeObserver", class { observe(): void { /* nothing to watch */ } unobserve(): void { /* nothing */ } disconnect(): void { /* nothing */ } });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function app(): void {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Board />
    </QueryClientProvider>,
  );
}

describe("the board's first state read", () => {
  it("fails once, then succeeds: the board shows and the offline line never appears", async () => {
    let states = 0;
    const offline = vi.fn();
    const fetchMock = vi.fn((input: string) => {
      if (input.startsWith("/api/state")) {
        states++;
        return Promise.resolve(states === 1 ? json({ ok: false }, 503) : json(real("state.json")));
      }
      return Promise.resolve(json({ ok: false }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    app();
    const watch = new MutationObserver(() => {
      if (screen.queryByText(/The hub is not answering/) !== null) offline();
    });
    watch.observe(document.body, { childList: true, subtree: true, characterData: true });
    await waitFor(() => { expect(screen.queryByText("Waits for you")).not.toBeNull(); }, { timeout: 4000 });
    watch.disconnect();
    expect(states).toBe(2);
    expect(offline).not.toHaveBeenCalled();
    expect(screen.queryByText(/The hub is not answering/)).toBeNull();
  });

  it("after the hub is gone for a while, the board comes back by itself within 10 s", async () => {
    let up = false;
    const fetchMock = vi.fn((input: string) => Promise.resolve(input.startsWith("/api/state") && up ? json(real("state.json")) : json({ ok: false }, 503)));
    vi.stubGlobal("fetch", fetchMock);
    app();
    await screen.findByText(/The hub is not answering/, undefined, { timeout: 4000 });
    up = true;
    await waitFor(() => { expect(screen.queryByText("Waits for you")).not.toBeNull(); }, { timeout: 10000 });
  }, 20000);
});
