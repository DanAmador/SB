import { expect, test, type Page } from "@playwright/test";

/** No run is live and the queue holds only a close-off job, as between runs; today has one run done and one short. */
async function between(page: Page): Promise<void> {
  await page.route("**/api/state", async (route) => {
    const res = await route.fetch();
    const s = (await res.json()) as { now: number; queue: { night: string | null; items: Record<string, unknown>[] } };
    // every link of a real item, all null: a job has no ticket, map or report
    const links = Object.fromEntries(Object.keys(s.queue.items[0]?.links ?? {}).map((k) => [k, null]));
    s.queue.night = null;
    s.queue.items = [
      // queued with no run live: it waits for Start
      { ...s.queue.items.find((i) => i.state === "queued"), night: undefined, waits: undefined },
      {
        key: "job:close-off", kind: "job", agent: null, state: "queued", note: "waits until 09:00", commit: null, tries: 0, started: null, ended: null,
        model: "sonnet", project: "/demo", repo: "/demo", prompt: "close the night", hash: "abc", name: "close-off", title: "Close off the night", close_off: true,
        created: s.now - 3000, waits: { kind: "time", with: null, text: "starts at 09:00" }, links,
      },
    ];
    await route.fulfill({ response: res, json: s });
  });
  await page.route("**/api/runs?*", async (route) => {
    const res = await route.fetch({ url: route.request().url().replace(/since=[\d.]+/, "since=0") });
    const page_ = (await res.json()) as { runs: Record<string, unknown>[] };
    const base = page_.runs[0];
    if (base === undefined) throw new Error("the fixture has no run to copy");
    const t = Date.now() / 1000;
    const runs = [
      { ...base, key: "demo/board#7", title: "Show who runs what", outcome: "done", reason: "", started: t - 1200, ended: t - 600 },
      { ...base, key: "other/site#4", title: "Check the shop's checkout", outcome: "failed", reason: "check failed", started: t - 900, ended: t - 300 },
    ];
    await route.fulfill({ response: res, json: { runs, total: 2, offset: 0, limit: 200 } });
  });
}

test("with no run live, the Now panel still shows the queued job and today's runs, and folds away", async ({ page }) => {
  await between(page);
  await page.goto("/next/");
  await expect(page.getByTestId("run-head")).toContainText("No run is live");
  await expect(page.getByTestId("outside-run")).toHaveText("Also in the queue: Close off the night.");
  const panel = page.getByRole("complementary", { name: "Now and next" });
  await expect(panel.getByRole("region", { name: "Running" })).toContainText("No worker is running.");
  const queued = panel.getByRole("region", { name: "Queued" });
  await expect(queued.getByRole("listitem")).toHaveCount(2);
  await expect(queued.getByRole("listitem").first()).toContainText("waits for Start");
  await expect(queued).toContainText("Close off the night");
  await expect(queued).toContainText("job · waits: starts at 09:00");
  const clock = panel.getByTestId("today-clock");
  await expect(clock.locator("[data-outcome=done]")).toHaveCount(1);
  await expect(clock.locator("[data-outcome=failed]")).toHaveCount(1);
  // the two runs overlap, so they sit side by side
  const [a, b] = await Promise.all([clock.locator("[data-outcome=done]").boundingBox(), clock.locator("[data-outcome=failed]").boundingBox()]);
  expect(a && b && Math.abs(a.x - b.x) > 10).toBe(true);
  await page.screenshot({ path: test.info().outputPath("now-1440.png") });

  // a block opens its run in History
  await clock.locator("[data-outcome=failed]").click();
  await expect(page).toHaveURL(/view=history/);
  await expect(page).toHaveURL(/run=other%2Fsite%234/);

  // folded, it stays folded after a reload, with the count on its button
  await panel.getByRole("button", { name: "Hide Now" }).click();
  await expect(panel.getByRole("region", { name: "Queued" })).toHaveCount(0);
  await page.reload();
  await panel.getByRole("button", { name: "Show Now: 2 queued" }).click();
  await expect(panel.getByRole("region", { name: "Queued" })).toContainText("Close off the night");
});

test("on a phone the Now panel is a fold above the view", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await between(page);
  await page.goto("/next/");
  await expect(page.getByRole("complementary", { name: "Now and next" })).toHaveCount(0);
  const fold = page.getByTestId("now-panel");
  await expect(fold.locator("summary")).toContainText("Now2 queued");
  await expect(fold.getByRole("region", { name: "Queued" })).toContainText("Close off the night");
  await fold.locator("summary").click();
  await expect(fold.getByRole("region", { name: "Queued" })).toBeHidden();
  await page.screenshot({ path: test.info().outputPath("now-375.png"), fullPage: true });
});
