import { describe, expect, it } from "vitest";
import type { QueueItem, Run } from "@sb-hub/contract";
import { dayBlocks, nowNext } from "./now.ts";

const item = (key: string, state: QueueItem["state"], more: Record<string, unknown> = {}): QueueItem =>
  ({ key, kind: "ticket", agent: null, state, note: "", commit: null, tries: 0, started: null, ended: null, ...more }) as unknown as QueueItem;
const run = (key: string, started: number | null, ended: number | null, more: Partial<Run> = {}): Run =>
  ({ key, title: `Run ${key}`, project: "p", map: "p/a", outcome: "done", reason: "", account: "main", model: null, started, ended, commit: null, tries: 1, refused: 0, refused_lines: [], pictures: [], ...more }) as unknown as Run;

describe("nowNext", () => {
  it("keeps what runs or is in checks and what is queued, in order, with or without a live run", () => {
    const items = [
      item("p/a#1", "done"), item("p/a#2", "running"), item("p/a#3", "landed"), item("p/a#4", "review"),
      item("job:close-off", "queued", { kind: "job" }), item("p/a#5", "queued"), item("p/a#6", "failed"),
    ];
    const n = nowNext(items);
    expect(n.running.map((i) => i.key)).toEqual(["p/a#2", "p/a#3", "p/a#4"]);
    expect(n.queued.map((i) => i.key)).toEqual(["job:close-off", "p/a#5"]);
  });
});

describe("dayBlocks", () => {
  const FROM = 1_000_000;
  const TO = FROM + 12 * 3600;
  const title = (i: QueueItem): string => `Item ${i.key}`;

  it("clips to the day, puts overlapping runs side by side and reuses a lane once it is free", () => {
    const { blocks, lanes } = dayBlocks(
      [
        run("a#1", FROM - 3600, FROM + 3600), // began yesterday
        run("a#2", FROM + 1800, FROM + 7200), // overlaps a#1
        run("a#3", FROM + 7200, FROM + 9000, { outcome: "failed" }), // starts as a#1's lane is free
        run("a#0", FROM - 7200, FROM - 3600), // ended yesterday
      ],
      [item("a#9", "running", { started: FROM + 8000, runner: "codex" })],
      title, FROM, TO,
    );
    expect(blocks.map((b) => [b.key, b.lane, b.start - FROM, b.end - FROM, b.outcome])).toEqual([
      ["a#1", 0, 0, 3600, "done"],
      ["a#2", 1, 1800, 7200, "done"],
      ["a#3", 0, 7200, 9000, "failed"],
      ["a#9", 1, 8000, TO - FROM, "running"],
    ]);
    expect(lanes).toBe(2);
    expect(blocks[3]?.title).toBe("Item a#9");
    expect(blocks[3]?.account).toBe("codex");
  });
  it("leaves out a run with no end, which the queue draws as running, and has one lane on an empty day", () => {
    expect(dayBlocks([run("a#1", FROM, null)], [], title, FROM, TO)).toEqual({ blocks: [], lanes: 1 });
  });
});
