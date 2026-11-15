import { expect, test } from "@playwright/test";

const SHOT = "/Users/danamador/Documents/Second Brain/wayfinder/sb-workflow/runs/2026-11-16-checks-in-the-repo/114-sidebar-375.png";

test("the sidebar lists every map in one list, running first, a stuck map with its reason", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.route("**/api/tickets", async (route) => {
    const res = await route.fetch();
    const rows = (await res.json()) as Record<string, unknown>[];
    const base = rows.find((r) => r.map === "demo/board");
    if (base) rows.push({ ...base, map: "demo/stuck", map_title: "A stuck map", num: 1, state: "waits for you", reason: "a grilling ticket needs you", queued: false, file: "/vault/demo/stuck/issues/1.md" });
    await route.fulfill({ response: res, json: rows });
  });
  await page.goto("/next/");
  await page.getByRole("button", { name: "Projects and maps" }).click();
  const nav = page.getByRole("navigation", { name: "Projects and maps" });
  await expect(nav.getByText("waits for you")).toBeVisible();
  await expect(nav.getByText(/quiet/)).toHaveCount(0);
  const titles = await nav.getByRole("button", { name: /^(?!Collapse|Expand|Everything|Active)/ }).allInnerTexts();
  expect(titles.findIndex((t) => t.includes("The demo board") || t.includes("board"))).toBeLessThan(titles.findIndex((t) => t.includes("stuck")));
  await nav.screenshot({ path: SHOT });
});
