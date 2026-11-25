/** Every route sbhub.py serves, with the body it takes and each answer by status. */
import { z } from "zod";
import * as s from "./schemas.ts";

type Answers = Readonly<Partial<Record<number, z.ZodType>>>;

interface RouteSpec {
  readonly body?: z.ZodType;
  /** json: a JSON answer; text: text/plain on 200; media: a picture or clip (an empty text/plain 404). */
  readonly kind: "json" | "text" | "media";
  readonly answers: Answers;
}

const json = <A extends Answers>(answers: A) => ({ kind: "json" as const, answers });
const text = <A extends Answers>(answers: A) => ({ kind: "text" as const, answers });
const post = <B extends z.ZodType, A extends Answers>(body: B, answers: A) => ({ kind: "json" as const, body, answers });

export const ROUTES = {
  "GET /api/state": json({ 200: s.State }),
  "GET /api/trail": json({ 200: s.Trail, 404: s.ApiError }),
  "GET /api/nights": json({ 200: s.NightsAnswer }),
  "GET /api/night": json({ 200: s.NightDetail, 404: s.ApiError }),
  "GET /api/runs": json({ 200: s.RunsPage }),
  "GET /api/run": json({ 200: s.RunDetail, 404: s.ApiError }),
  "GET /api/tickets": json({ 200: s.Tickets }),
  "GET /api/map": json({ 200: s.MapRoute, 404: s.ApiError }),
  "GET /api/ticket": json({ 200: s.TicketDetail, 404: s.ApiError }),
  "GET /api/item/report": text({ 200: s.ItemText, 404: s.ApiError }),
  "GET /api/item/log": text({ 200: s.ItemText, 404: s.ApiError }),
  "GET /api/item/feed": json({ 200: s.ItemFeed, 404: s.ApiError }),
  "GET /api/media": { kind: "media" as const, answers: { 200: s.MediaType, 206: s.MediaType, 404: z.literal(""), 416: z.literal("") } },
  "GET /api/question/:id": json({ 200: s.Question, 404: s.ApiError }),

  "POST /api/report": post(s.ReportBody, { 200: s.ReportAnswer }),
  "POST /api/lock": post(s.LockBody, { 200: s.Ok, 409: s.LockHeld }),
  "POST /api/unlock": post(s.LockBody, { 200: s.Ok }),
  "POST /api/ask": post(s.AskBody, { 200: s.IdAnswer }),
  "POST /api/answer": post(s.AnswerBody, { 200: s.Ok, 404: s.ApiError }),
  "POST /api/send": post(s.SendBody, { 200: s.IdAnswer }),
  "POST /api/unsend": post(s.UnsendBody, { 200: s.Ok, 404: s.ApiError }),
  "POST /api/take": post(s.TakeBody, { 200: s.TakeAnswer }),
  "POST /api/queue/set": post(s.QueueSetBody, { 200: s.QueueAnswer, 409: s.QueueStale }),
  "POST /api/queue/move": post(s.QueueMoveBody, { 200: s.QueueAnswer, 409: s.QueueStale }),
  "POST /api/queue/map": post(s.QueueMapBody, { 200: s.QueueMapAnswer, 409: s.QueueStale }),
  "POST /api/queue/move_map": post(s.QueueMoveMapBody, { 200: s.QueueAnswer, 409: s.QueueStale }),
  "POST /api/queue/pause": post(s.QueuePauseBody, { 200: s.QueueAnswer }),
  "POST /api/queue/parallel": post(s.QueueParallelBody, { 200: s.QueueAnswer, 409: s.QueueStale }),
  "POST /api/queue/agent": post(s.QueueAgentBody, { 200: s.QueueAnswer }),
  "POST /api/queue/agents": post(s.QueueAgentsBody, { 200: s.QueueAnswer, 409: s.QueueStale }),
  "POST /api/queue/options": post(s.QueueOptionsBody, { 200: s.QueueAnswer, 409: s.QueueStale }),
  "POST /api/queue/job": post(s.QueueJobBody, { 200: s.QueueJobAnswer }),
  "POST /api/queue/integrate": post(s.QueueIntegrateBody, { 200: s.QueueIntegrateAnswer }),
  "POST /api/queue/remove_job": post(s.QueueRemoveJobBody, { 200: s.QueueAnswer, 409: s.QueueStale }),
  "POST /api/queue/stop": post(s.QueueStopBody, { 200: s.QueueAnswer, 409: s.QueueStale }),
  "POST /api/night/start": post(s.NightStartBody, { 200: s.NightAnswer }),
  "POST /api/night/stop": post(s.NightStopBody, { 200: s.NightAnswer }),
  "POST /api/night/rename": post(s.NightRenameBody, { 200: s.NightAnswer }),
  "POST /api/run/join": post(s.RunJoinBody, { 200: s.RunJoinAnswer }),
  "POST /api/run/leave": post(s.RunLeaveBody, { 200: s.Ok }),
  "POST /api/run/integrate": post(s.RunIntegrateBody, { 200: s.QueueAnswer }),
  "POST /api/run/take": post(s.RunTakeBody, { 200: s.RunTakeAnswer }),
  "POST /api/run/done": post(s.RunDoneBody, { 200: s.QueueAnswer }),
  "POST /api/queue/item_agent": post(s.QueueItemAgentBody, { 200: s.QueueAnswer }),
  "POST /api/run/seen": post(s.RunSeenBody, { 200: s.Ok }),
  "POST /api/agents/dismiss": post(s.AgentsDismissBody, { 200: s.Ok }),
  "POST /api/agents/clear-quiet": post(s.EmptyBody, { 200: s.ClearQuietAnswer }),
  "POST /api/agents/scan": post(s.EmptyBody, { 200: s.ScanAnswer }),
  "POST /api/review/now": post(s.EmptyBody, { 200: s.ReviewNowAnswer }),
  "POST /api/ticket/:action": post(s.TicketActionBody, { 200: s.TicketActionOut }),
} as const satisfies Record<string, RouteSpec>;

export type RouteName = keyof typeof ROUTES;

type Spec<K extends RouteName> = (typeof ROUTES)[K];
/** The body a POST route takes. */
export type RouteBody<K extends RouteName> = Spec<K> extends { body: infer B extends z.ZodType } ? z.infer<B> : never;
/** What a route answers with a given status. */
export type RouteAnswer<K extends RouteName, S extends number = 200> =
  Spec<K>["answers"] extends Record<S, infer A extends z.ZodType> ? z.infer<A> : never;

/** Any 400, 403, 404 or 500 a route does not list answers with ApiError. */
const ERRORS = new Set([400, 403, 404, 500]);

/** The route a request goes to: "GET /api/question/ab12" is "GET /api/question/:id". */
export function routeOf(method: string, path: string): RouteName | undefined {
  const bare = path.split("?", 1)[0] ?? "";
  const exact = `${method} ${bare}`;
  if (exact in ROUTES) return exact as RouteName;
  if (method === "GET" && /^\/api\/question\/[^/]+$/.test(bare)) return "GET /api/question/:id";
  const action = /^\/api\/ticket\/([^/]+)$/.exec(bare)?.[1];
  if (method === "POST" && action !== undefined && s.TicketAction.safeParse(action).success) return "POST /api/ticket/:action";
  return undefined;
}

/** The schema a route's answer with this status must parse with, or undefined for a status it never gives. */
export function answerSchema(route: RouteName, status: number): z.ZodType | undefined {
  const answers: Answers = ROUTES[route].answers;
  return answers[status] ?? (ERRORS.has(status) && ROUTES[route].kind !== "media" ? s.ApiError : undefined);
}

/** The schema of a POST route's body. */
export function bodySchema(route: RouteName): z.ZodType | undefined {
  const spec: RouteSpec = ROUTES[route];
  return spec.body;
}
