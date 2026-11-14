import { afterEach, describe, expect, it, vi } from "vitest";

async function load(pathname: string, widget = false): Promise<typeof import("./api.ts")> {
  vi.resetModules();
  window.history.replaceState(null, "", pathname);
  if (widget) Object.assign(window, { __SB_WIDGET__: true });
  return import("./api.ts");
}

afterEach(() => {
  Reflect.deleteProperty(window, "__SB_WIDGET__");
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
});

describe("read-only pages", () => {
  it("the phone page reads under /v/<token>/ and refuses every write without asking the hub", async () => {
    const fetchMock = vi.fn(() => Promise.reject(new Error("no network in this test")));
    vi.stubGlobal("fetch", fetchMock);
    const api = await load("/v/abc_DEF-123/");
    expect(api.READONLY).toBe(true);
    expect(api.mediaUrl("m#1", "a.png")).toBe("/v/abc_DEF-123/api/media?key=m%231&name=a.png");
    const out = await api.post("POST /api/answer", { qid: "q", answer: "x" });
    expect(out).toMatchObject({ ok: false, status: 403, error: "this page is read-only" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("the board at /next/ writes", async () => {
    const api = await load("/next/");
    expect(api.READONLY).toBe(false);
    expect(api.mediaUrl("m#1", "a.png")).toBe("/api/media?key=m%231&name=a.png");
  });

  it("the chat widget is read-only except for answering a question", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response('{"ok":true}', { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    const api = await load("/", true);
    expect(api.READONLY).toBe(true);
    expect(await api.post("POST /api/queue/pause", { paused: true })).toMatchObject({ ok: false, status: 403 });
    expect(fetchMock).not.toHaveBeenCalled();
    expect((await api.post("POST /api/answer", { qid: "q", answer: "x" })).ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
