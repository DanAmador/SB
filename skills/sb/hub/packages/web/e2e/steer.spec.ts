import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

/** The Steer block against a real vault: the fixture hub runs the real Hub and sbmap on a throwaway map. */
test.describe.configure({ mode: "serial" });

const noteOf = async (page: Page, num: number): Promise<string> => {
  const { vault } = (await (await page.request.get("/api/__vault")).json()) as { vault: string };
  const dir = join(vault, "wayfinder", "steer", "lab", "issues");
  const file = readdirSync(dir).find((f) => f.startsWith(String(num).padStart(3, "0")));
  if (file === undefined) throw new Error(`no note ${String(num)}`);
  return readFileSync(join(dir, file), "utf8");
};
const panel = async (page: Page, key: string): Promise<ReturnType<Page["getByRole"]>> => {
  await page.goto(`/next/?t=${encodeURIComponent(key)}`);
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByRole("region", { name: "Steer" })).toBeVisible();
  return sheet.getByRole("region", { name: "Steer" });
};
const today = new Date().toLocaleDateString("sv");
/** A save runs the real sbmap: on a loaded machine (2026-11-20, load ~48) one took over 5 s, so wait longer for its result. */
const SAVED = { timeout: 20_000 };

test("Done when, files and what it comes after change from the panel and the note on disk shows each", async ({ page }) => {
  // Three real sbmap writes: the 30 s default ran out under load, and a retry cannot help, as the first try already
  // changed the note on disk.
  test.slow();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const steer = await panel(page, "steer/lab#1");
  await expect(steer.getByTestId("steer-done_when")).toHaveText("It stands.");

  // Done when: Edit, a field, Save, a confirmation
  await steer.getByRole("button", { name: "Edit Done when" }).click();
  await steer.getByRole("textbox").fill("The wall stands\nand the test passes.");
  await steer.getByRole("button", { name: "Save…" }).click();
  await steer.getByRole("button", { name: "Yes, save it" }).click();
  await expect(steer.getByTestId("steer-done_when")).toContainText("The wall stands", SAVED);
  let note = await noteOf(page, 1);
  expect(note).toContain("## Done when\n\nThe wall stands\nand the test passes.\n");
  expect(note).toContain(`- **${today}**: Owner changed Done when from the hub; it was: It stands.`);

  // files: one per line
  await steer.getByRole("button", { name: "Edit Files" }).click();
  await steer.getByRole("textbox").fill("src/a.py\ndocs/");
  await steer.getByRole("button", { name: "Save…" }).click();
  await steer.getByRole("button", { name: "Yes, save it" }).click();
  await expect(steer.getByTestId("steer-paths")).toContainText("docs/", SAVED);
  note = await noteOf(page, 1);
  expect(note).toMatch(/paths:\n\s+- src\/a\.py\n\s+- docs\//);
  expect(note).toContain("Owner changed files from the hub; it was: src/");

  // what it comes after: tickets of the map, picked by title
  await steer.getByRole("button", { name: "Edit Comes after" }).click();
  await steer.getByRole("checkbox", { name: "Build the wall" }).check();
  await steer.getByRole("button", { name: "Save…" }).click();
  await steer.getByRole("button", { name: "Yes, save it" }).click();
  await expect(steer.getByTestId("steer-after")).toHaveText("Build the wall", SAVED);
  note = await noteOf(page, 1);
  expect(note).toContain("blocked_by:");
  expect(note).toContain("Owner changed what it comes after from the hub; it was: empty");
  expect(errors).toEqual([]);
});

test("a loop in the order is refused with sbmap's words and the note is left as it was", async ({ page }) => {
  const steer = await panel(page, "steer/lab#2"); // #1 now waits for #2 (and #3 waits for #2)
  const before = await noteOf(page, 2);
  await steer.getByRole("button", { name: "Edit Comes after" }).click();
  await steer.getByRole("checkbox", { name: "Lay the base" }).check();
  await steer.getByRole("button", { name: "Save…" }).click();
  await steer.getByRole("button", { name: "Yes, save it" }).click();
  await expect(steer.getByRole("alert")).toContainText("it would be a loop", SAVED);
  await page.screenshot({ path: "/tmp/steer-loop-desktop.png" });
  expect(await noteOf(page, 2)).toBe(before);
});

test("a running ticket's Done when changes and its worker is told; the order waits until it stops", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/next/?t=demo%2Fboard%235");
  const sheet = page.getByRole("dialog");
  const steer = sheet.getByRole("region", { name: "Steer" });
  await expect(steer).toContainText("a change to Done when or Files is saved and sent to it");
  await expect(steer.getByRole("button", { name: "Edit Comes after" })).toBeDisabled();
  await expect(steer.getByRole("button", { name: "Edit Files" })).toBeEnabled();
  await steer.getByRole("button", { name: "Edit Done when" }).click();
  await steer.getByRole("textbox").fill("The cleared-job row shows in the board test.");
  await steer.getByRole("button", { name: "Save…" }).click();
  await expect(steer.getByRole("alert")).toContainText("Its worker gets the new one as a message.");
  await steer.getByRole("button", { name: "Yes, save it" }).click();
  const told = sheet.getByRole("region", { name: "Live" }).getByRole("list", { name: "Your messages to it" });
  await expect(told).toContainText("changed your ticket's Done when");
  await expect(told).toContainText("The cleared-job row shows in the board test.");
  expect(errors).toEqual([]);
});

test("Steer fits a phone: no sideways scroll at 375 px, in light and dark", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    const steer = await panel(page, "steer/lab#3");
    await steer.getByRole("button", { name: "Edit Comes after" }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(await page.getByRole("dialog").evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    await steer.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `/tmp/steer-${scheme}-375.png` });
  }
});
