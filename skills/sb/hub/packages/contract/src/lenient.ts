import type { ZodType } from "zod";

/**
 * Reads `value` with the strict schema, and when the only fault is keys the schema does not know, drops them and reads
 * again. A missing key, a wrong type or a wrong value still fails. `unknown` names each dropped key ("queue.items.0.x");
 * `value` is the input without them. The schemas themselves stay strict: the contract tests use them as they are.
 */
export type Lenient =
  | { readonly ok: true; readonly value: unknown; readonly unknown: readonly string[] }
  | { readonly ok: false; readonly error: { readonly issues: readonly { readonly path: readonly PropertyKey[]; readonly message: string }[] } };

export function lenient(schema: ZodType, input: unknown): Lenient {
  const first = schema.safeParse(input);
  if (first.success) return { ok: true, value: input, unknown: [] };
  let r: ReturnType<typeof schema.safeParse> = first;
  let value: unknown = input;
  const dropped: string[] = [];
  for (let round = 0; round < 20 && !r.success; round++) {
    const issues = r.error.issues;
    if (!issues.every((i) => i.code === "unrecognized_keys")) break;
    if (value === input) value = structuredClone(input);
    for (const i of issues) {
      let at: unknown = value;
      for (const p of i.path) at = (at as Record<PropertyKey, unknown> | undefined)?.[p];
      for (const k of i.keys) {
        if (typeof at === "object" && at !== null) Reflect.deleteProperty(at, k);
        dropped.push([...i.path, k].join("."));
      }
    }
    r = schema.safeParse(value);
  }
  return r.success ? { ok: true, value, unknown: dropped } : { ok: false, error: first.error };
}
