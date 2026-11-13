import { expect, it } from "vitest";
import { hubHome, hubPort } from "./config.ts";

it("listens on 8765 unless told otherwise", () => {
  expect(hubPort([], {})).toBe(8765);
  expect(hubPort([], { SB_HUB_PORT: "9001" })).toBe(9001);
  expect(hubPort(["--port", "9002"], { SB_HUB_PORT: "9001" })).toBe(9002);
});

it("falls back to 8765 for a value that is not a port, as sbhub.py does", () => {
  for (const bad of ["", "0", "70000", "abc", "80.5"]) expect(hubPort([], { SB_HUB_PORT: bad })).toBe(8765);
});

it("keeps its state where sbhub.py does", () => {
  expect(hubHome({ SB_HUB_HOME: "/tmp/hub" })).toBe("/tmp/hub");
  expect(hubHome({})).toMatch(/\.sb-hub$/);
});
