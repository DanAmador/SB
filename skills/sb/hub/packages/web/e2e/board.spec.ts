import { expect, test, type Page } from "@playwright/test";

/** Tests share one fixture hub; they run one after another, in this order. */
test.describe.configure({ mode: "serial" });

const queuedKeys = async (page: Page): Promise<string[]> => {
  const state = (await (await page.request.get("/api/state")).json()) as { queue: { items: { key: string; state: string }[] } };
  return state.queue.items.filter((i) => i.state === "queued").map((i) => i.key);
};

test("Runs is the landing page: one row per worker run, the silent one amber, never a chat session", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/next/");
  await expect(page.getByRole("tab", { name: /Runs/ })).toHaveAttribute("aria-selected", "true");
  const runs = page.getByRole("list", { name: "Running now" });
  await expect(runs.getByRole("listitem")).toHaveCount(2);
  // the silent one first, amber, with its last action and when
  const silent = runs.getByRole("listitem").first();
  await expect(silent).toContainText("Read the accounts' usage");
  await expect(silent.getByRole("img", { name: "no report for 5 minutes or more" })).toBeVisible();
  await expect(silent).toContainText("reading the usage file");
  const busy = runs.getByRole("listitem").nth(1);
  await expect(busy).toContainText("running the tests");
  await expect(busy).toContainText("12 min");
  await expect(busy).toContainText("opus");
  await expect(busy.getByRole("link", { name: "Open the ticket in Obsidian" })).toHaveAttribute("href", "obsidian://open?path=%2Fvault%2Fdemo%2Fboard%2Fissues%2F5.md");
  await expect(busy.getByRole("link", { name: "Log" })).toHaveAttribute("href", /^obsidian:\/\/open\?path=%2Fvault%2Fruns%2F2026-11-13-board%2F5\.log$/);
  // your chat session is not a run
  await expect(page.getByText("Charting the board")).toHaveCount(0);
  // the Waits for you count is the page's alarm: a question, a failed run, a done run
  await expect(page.getByRole("tab", { name: /Waits for you/ })).toContainText("3");
  // a row opens the ticket's panel, with Message and Stop
  await busy.getByRole("button", { name: "Run the board against the real hub", exact: true }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByRole("link", { name: "Ticket" })).toHaveAttribute("href", /^obsidian:/);
  await expect(sheet.getByRole("link", { name: "Map" })).toHaveAttribute("href", /^obsidian:/);
  await sheet.getByRole("button", { name: "Stop" }).click();
  await sheet.getByRole("button", { name: "Yes, stop it" }).click();
  await expect(sheet.getByText("Asked to stop: it reads that after its next tool call.").first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("a ticket found by the Queue's search and dragged into Up next lands at that place, and the hub has it", async ({ page }) => {
  await page.goto("/next/?view=queue");
  const next = page.getByTestId("up-next");
  await expect(next.getByText("Show the queue in order")).toBeVisible();
  await page.getByRole("searchbox", { name: /Find an open ticket/ }).fill("drag");
  await expect(page).toHaveURL(/q=drag/);
  const found = page.getByTestId("found");
  await expect(found.getByRole("listitem")).toHaveCount(1);
  await found.locator("li", { hasText: "Drag a ticket into the queue" }).dragTo(next.locator("li", { hasText: "Show the queue in order" }));
  await expect(next.locator("li").first()).toContainText("Drag a ticket into the queue");
  await expect(next.locator("li").nth(1)).toContainText("Show the queue in order");
  await expect(page.getByRole("status")).toContainText("Queued.");
  expect(await queuedKeys(page)).toEqual(["demo/board#2", "demo/board#3"]);

  // drag to reorder
  await next.locator("li", { hasText: "Show the queue in order" }).dragTo(next.locator("li", { hasText: "Drag a ticket into the queue" }));
  await expect(next.locator("li").first()).toContainText("Show the queue in order");
  expect(await queuedKeys(page)).toEqual(["demo/board#3", "demo/board#2"]);
});

test("the search's filters live in the page link; one click queues; the panel opens as a sheet", async ({ page }) => {
  await page.goto("/next/?view=queue&q=header");
  const found = page.getByTestId("found");
  await expect(found.getByRole("button", { name: "Draw the header", exact: true })).toBeVisible();
  await page.getByRole("radio", { name: /Needs a decision/ }).click();
  await expect(page).toHaveURL(/s=waits/);
  await expect(page.getByText("No open ticket here matches.")).toBeVisible();
  await page.getByRole("radio", { name: /Can run/ }).click();
  await found.getByRole("button", { name: "Draw the header", exact: true }).click();
  await expect(page).toHaveURL(/t=demo%2Fboard%231/);
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByRole("heading", { name: "Draw the header" })).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Queue it" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await expect(page).not.toHaveURL(/t=/);
  await found.getByRole("button", { name: "Queue Draw the header", exact: true }).click();
  await expect(page.getByTestId("up-next").getByText("Draw the header")).toBeVisible();
});

test("Waits for you: the question first, then the failed run in plain words, then the done run with its checks", async ({ page }) => {
  await page.goto("/next/?view=waits");
  const parts = page.locator("main section h2");
  await expect(parts).toHaveText(["Questions", "Failed", "Done", "Tickets that need a decision"]);
  await expect(page.getByRole("article", { name: /Question from Charting the board/ })).toBeVisible();
  const failed = page.getByRole("region", { name: "Failed" });
  await expect(failed.getByText("ended without a commit")).toBeVisible();
  await expect(failed.getByRole("button", { name: "Run again" })).toBeVisible();
  const done = page.getByRole("region", { name: "Done" });
  await expect(done.getByText("1 check passed")).toBeVisible();
  await done.getByRole("button", { name: "Looks good" }).click();
  await expect(page.getByRole("region", { name: "Done" })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: /Waits for you/ })).toContainText("2");
});

test("Cmd-K opens the command menu with New job and Message", async ({ page }) => {
  await page.goto("/next/");
  await expect(page.getByRole("list", { name: "Running now" })).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  const menu = page.getByRole("dialog");
  await expect(menu.getByRole("option", { name: "New job" })).toBeVisible();
  await menu.getByRole("option", { name: /Message/ }).click();
  await expect(page.getByRole("dialog").getByRole("heading", { name: "Message" })).toBeVisible();
});

for (const [view, scheme] of [["runs", "light"], ["queue", "dark"], ["waits", "light"], ["waits", "dark"]] as const) {
  test(`axe finds no serious or critical issue on ${view} (${scheme})`, async ({ page }) => {
    const { default: AxeBuilder } = await import("@axe-core/playwright");
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto(`/next/?view=${view}`);
    await expect(page.getByRole("tab", { selected: true })).toBeVisible();
    await page.waitForTimeout(500);
    const r = await new AxeBuilder({ page }).analyze();
    const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
  });
}
