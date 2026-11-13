import { expect, it } from "vitest";
import { health } from "./health.ts";

it("reports ok", () => {
  expect(health()).toEqual({ ok: true, contract: 0 });
});
