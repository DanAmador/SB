import { describe, expect, it } from "vitest";
import { CONTRACT_VERSION, type Health } from "./index.ts";

describe("contract", () => {
  it("exposes a version", () => {
    const h: Health = { ok: true, contract: CONTRACT_VERSION };
    expect(h.contract).toBe(0);
  });
});
