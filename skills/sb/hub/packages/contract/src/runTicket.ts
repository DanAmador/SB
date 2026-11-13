/**
 * What `python3 skills/sb/scripts/sbhub.py run-ticket` prints: one ticket run to its end (RunTicketResult), a
 * detached start (RunTicketDetached) and a detached run read back with --status (RunTicketStatus). The server
 * decides what runs next; Python runs it and answers with these.
 */
import { z } from "zod";
import { CheckRun, Seconds } from "./schemas.ts";

/**
 * done: resolved; failed: left open with a comment; skipped: never started (not ready, claimed, gone) or changed
 * while it ran; retry: run it again on `retry.model`; stopped: its agent hit a usage limit or a logout, run it
 * again on any agent that fits.
 */
export const RunTicketState = z.enum(["done", "failed", "skipped", "retry", "stopped"]);
export type RunTicketState = z.infer<typeof RunTicketState>;

export const RunTicketStop = z.strictObject({
  kind: z.enum(["limit", "auth"]),
  agent: z.string(),
  /** When the agent may run again; null after a logout (it waits for the owner to sign in). */
  until: Seconds.nullable(),
});
export type RunTicketStop = z.infer<typeof RunTicketStop>;

export const RunTicketResult = z.strictObject({
  key: z.string(),
  state: RunTicketState,
  note: z.string(),
  commit: z.string().nullable(),
  /** Every check the verdict ran, with the end of its output. */
  checks: z.array(CheckRun),
  /** Names of the pictures and clips in <run>/<num>-media. */
  media: z.array(z.string()),
  retry: z.strictObject({ model: z.string(), reason: z.string() }).nullable(),
  stop: RunTicketStop.nullable(),
  agent: z.string().nullable(),
  model: z.string().nullable(),
  /** This try's number: 1 for the first. */
  tries: z.number().int().positive(),
  /** Stops at a limit or a logout so far, this one included. */
  stops: z.number().int().nonnegative(),
  base: z.string().nullable(),
  log: z.string().nullable(),
  /** The worker's report in the run folder, when it wrote one. */
  report: z.string().nullable(),
  run: z.string().nullable(),
  tree: z.string().nullable(),
  branch: z.string().nullable(),
});
export type RunTicketResult = z.infer<typeof RunTicketResult>;

export const RunTicketDetached = z.strictObject({
  pid: z.number().int(),
  /** The command's own stderr. */
  log: z.string(),
  /** Where its RunTicketResult lands. */
  result: z.string(),
  status: z.string(),
});
export type RunTicketDetached = z.infer<typeof RunTicketDetached>;

export const RunTicketStatus = z.strictObject({
  pid: z.number().int(),
  /** false: no detached run has this pid (exit 1). */
  known: z.boolean(),
  running: z.boolean(),
  key: z.string().nullable(),
  log: z.string().nullable(),
  worker: z.strictObject({ pid: z.number().int(), log: z.string(), agent: z.string() }).nullable(),
  result: RunTicketResult.nullable(),
  note: z.string(),
});
export type RunTicketStatus = z.infer<typeof RunTicketStatus>;
