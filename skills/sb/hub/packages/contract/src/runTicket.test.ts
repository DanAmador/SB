/**
 * Every answer `sbhub.py run-ticket` gave in tests/test_run_ticket.py parses with its schema: fixtures/run-ticket/
 * holds results (by state), the detached start and --status answers.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { RunTicketDetached, RunTicketResult, RunTicketState, RunTicketStatus } from "./index.ts";

const dir = join(import.meta.dirname, "..", "fixtures", "run-ticket");
const fixtures = readdirSync(dir)
  .filter((f) => f.endsWith(".json"))
  .sort()
  .map((f): [string, unknown] => [f, JSON.parse(readFileSync(join(dir, f), "utf8"))]);

function schemaFor(name: string) {
  if (name === "detached.json") return RunTicketDetached;
  if (name.startsWith("status-")) return RunTicketStatus;
  return RunTicketResult;
}

describe("run-ticket answers written by the hub", () => {
  it.each(fixtures)("%s parses with its schema", (name, body) => {
    schemaFor(name).parse(body);
  });

  it("cover every state", () => {
    const states = new Set<string>();
    for (const [name, body] of fixtures) {
      if (name === "detached.json") continue;
      const result = name.startsWith("status-") ? RunTicketStatus.parse(body).result : RunTicketResult.parse(body);
      if (result) states.add(result.state);
    }
    expect([...states].sort()).toEqual([...RunTicketState.options].sort());
  });

  it("refuse a renamed field", () => {
    const done = fixtures.find(([f]) => f === "done.json")?.[1] as Record<string, unknown>;
    const { commit, ...rest } = done;
    expect(RunTicketResult.safeParse({ ...rest, sha: commit }).success).toBe(false);
  });
});
