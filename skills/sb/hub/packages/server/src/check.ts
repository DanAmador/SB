/** Whether an answer from the Python hub is one the contract allows. */
import { ApiError, answerSchema, lenient, ROUTES, routeOf, type RouteName } from "@sb-hub/contract";

type Schema = NonNullable<ReturnType<typeof answerSchema>>;

export interface Answer {
  readonly status: number;
  readonly contentType: string;
  readonly body: Buffer;
}

/** `value` is set when the answer had keys the contract does not know: the answer without them, and their names. */
export type Verdict = { readonly ok: true; readonly value?: unknown; readonly unknown?: readonly string[] } | { readonly ok: false; readonly route: string; readonly problem: string };

const mime = (contentType: string): string => (contentType.split(";", 1)[0] ?? "").trim().toLowerCase();

function parsed(schema: Schema, value: unknown, route: string): Verdict {
  const r = lenient(schema, value);
  if (r.ok) return r.unknown.length === 0 ? { ok: true } : { ok: true, value: r.value, unknown: r.unknown };
  const where = r.error.issues.slice(0, 3).map((i) => `${i.path.join(".") || "(answer)"}: ${i.message}`);
  return { ok: false, route, problem: where.join("; ") };
}

function json(a: Answer, schema: Schema, route: string): Verdict {
  if (mime(a.contentType) !== "application/json") return { ok: false, route, problem: `content type ${a.contentType || "(none)"}, not JSON` };
  let value: unknown;
  try {
    value = JSON.parse(a.body.toString("utf8"));
  } catch {
    return { ok: false, route, problem: "the body is not JSON" };
  }
  return parsed(schema, value, route);
}

/** Checks one answer against the route's schema for its status. A path no route names must be the hub's 404. */
export function checkAnswer(method: string, path: string, a: Answer): Verdict {
  const route: RouteName | undefined = routeOf(method, path);
  if (route === undefined) {
    const name = `${method} ${path.split("?", 1)[0] ?? ""}`;
    return a.status === 404 || a.status === 400 ? json(a, ApiError, name) : { ok: false, route: name, problem: `status ${String(a.status)} on a route the contract does not name` };
  }
  const schema = answerSchema(route, a.status);
  if (schema === undefined) return { ok: false, route, problem: `status ${String(a.status)} is not one this route gives` };
  const kind = ROUTES[route].kind;
  if (kind === "media") {
    if (a.status === 200 || a.status === 206) return parsed(schema, mime(a.contentType), route);
    return parsed(schema, a.body.toString("utf8"), route);
  }
  if (kind === "text" && a.status === 200) {
    if (mime(a.contentType) !== "text/plain") return { ok: false, route, problem: `content type ${a.contentType || "(none)"}, not text` };
    return parsed(schema, a.body.toString("utf8"), route);
  }
  return json(a, schema, route);
}
