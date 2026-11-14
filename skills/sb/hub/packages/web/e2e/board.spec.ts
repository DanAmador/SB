import { expect, test, type Page } from "@playwright/test";

/** Tests share one fixture hub; they run one after another, in this order. */
test.describe.configure({ mode: "serial" });

const queuedKeys = async (page: Page): Promise<string[]> => {
  const state = (await (await page.request.get("/api/state")).json()) as { queue: { items: { key: string; state: string }[] } };
  return state.queue.items.filter((i) => i.state === "queued").map((i) => i.key);
};

// the hub keeps the seen marks, so every test starts with none
test.beforeEach(async ({ request }) => {
  await request.post("/api/__reset-seen");
});

test("Runs is the landing page: one row per worker run, the silent one amber, never a chat session", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/next/");
  await expect(page.getByRole("tab", { name: /Runs/ })).toHaveAttribute("aria-selected", "true");
  const runs = page.getByRole("list", { name: "Running now" });
  await expect(runs.getByRole("listitem")).toHaveCount(3);
  // the silent one first, amber, with its last action and when
  const silent = runs.getByRole("listitem").first();
  await expect(silent).toContainText("Read the accounts' usage");
  await expect(silent.getByRole("img", { name: "no report for 5 minutes or more" })).toBeVisible();
  await expect(silent).toContainText("reading the usage file");
  const busy = runs.getByRole("listitem").filter({ hasText: "running the tests" });
  await expect(busy).toContainText("running the tests");
  await expect(busy).toContainText("12 min");
  await expect(busy).toContainText("opus");
  await expect(busy.getByRole("link", { name: "Run the board against the real hub" })).toHaveAttribute("href", "obsidian://open?path=%2Fvault%2Fdemo%2Fboard%2Fissues%2F5.md");
  await expect(busy.getByRole("link", { name: "Log" })).toHaveAttribute("href", /^obsidian:\/\/open\?path=%2Fvault%2Fruns%2F2026-11-13-board%2F5\.log$/);
  // your chat session is not a run
  await expect(page.getByText("Charting the board")).toHaveCount(0);
  // the Waits for you count is the page's alarm: a question, a failed run, a done run
  await expect(page.getByRole("tab", { name: /Waits for you/ })).toContainText("4");
  // a row opens the ticket's panel, with Message and Stop
  await busy.getByRole("button", { name: "Show details" }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByRole("link", { name: "Open in Obsidian" }).first()).toHaveAttribute("href", /^obsidian:/);
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
  // the title opens the ticket in Obsidian
  await expect(found.getByRole("link", { name: "Draw the header", exact: true })).toHaveAttribute("href", "obsidian://open?path=%2Fvault%2Fdemo%2Fboard%2Fissues%2F1.md");
  await page.getByRole("radio", { name: /Needs a decision/ }).click();
  await expect(page).toHaveURL(/s=waits/);
  await expect(page.getByText("No open ticket here matches.")).toBeVisible();
  await page.getByRole("radio", { name: /Can run/ }).click();
  await found.getByRole("button", { name: "Show details" }).click();
  await expect(page).toHaveURL(/t=demo%2Fboard%231/);
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByRole("heading", { name: "Draw the header" })).toBeVisible();
  // a digest: Open in Obsidian first, no ticket body of its own
  await expect(sheet.getByRole("navigation", { name: "In Obsidian" }).getByRole("link").first()).toHaveText("Open in Obsidian");
  await expect(sheet.getByText("Done when")).toHaveCount(0);
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
  await expect(page.getByRole("tab", { name: /Waits for you/ })).toContainText("3");

  // Open the run: it is marked seen, so it leaves Waits for you and sits in History
  await page.getByRole("region", { name: "Failed" }).getByRole("button", { name: "Open the run" }).first().click();
  await expect(page).toHaveURL(/view=history/);
  await page.goto("/next/?view=waits");
  await expect(page.getByRole("region", { name: "Failed" }).getByRole("listitem")).toHaveCount(1);
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

test("the sidebar picks a map and every view narrows; the pick lives in the page link and the x clears it", async ({ page }) => {
  await page.goto("/next/");
  const side = page.getByRole("navigation", { name: "Projects and maps" });
  // Everything, then each project with its maps and two counts each
  await expect(side.getByRole("button", { name: "Everything" })).toHaveAttribute("aria-current", "page");
  const shop = side.getByRole("button", { name: /^other/ });
  await expect(shop.getByLabel("1 running")).toBeVisible();
  await expect(shop.getByLabel("1 waiting for you")).toBeVisible();
  await expect(page.getByRole("list", { name: "Running now" }).getByRole("listitem")).toHaveCount(3);

  // collapse a project: its maps go
  await side.getByRole("button", { name: "Collapse other" }).click();
  await expect(side.getByRole("button", { name: /^site/ })).toHaveCount(0);
  await side.getByRole("button", { name: "Expand other" }).click();

  // pick a map: Runs narrows, and the link holds it
  await side.getByRole("button", { name: /^site/ }).click();
  await expect(page).toHaveURL(/project=other&map=other%2Fsite/);
  const runs = page.getByRole("list", { name: "Running now" });
  await expect(runs.getByRole("listitem")).toHaveCount(1);
  await expect(runs).toContainText("Write the shop's copy");
  const crumb = page.getByRole("navigation", { name: "Breadcrumb" });
  await expect(crumb).toContainText("other");
  await expect(crumb).toContainText("site");
  await expect(page.getByRole("tab", { name: /Runs/ })).toContainText("1");

  // Queue: its search finds only this map's open tickets; Up next has none of the other map's
  await page.keyboard.press("2");
  await expect(page).toHaveURL(/view=queue/);
  const found = page.getByTestId("found");
  await expect(found.getByRole("listitem")).toHaveCount(1);
  await expect(found).toContainText("Draw the shop window");
  await expect(found).not.toContainText("Draw the header");
  await expect(page.getByTestId("up-next")).not.toContainText("Show the queue in order");

  // Waits for you: the shop's failed run only, no question, no done run
  await page.keyboard.press("3");
  await expect(page.getByRole("region", { name: "Failed" }).getByRole("listitem")).toHaveCount(1);
  await expect(page.getByRole("region", { name: "Failed" })).toContainText("pnpm test failed");
  await expect(page.getByRole("region", { name: "Done" })).toHaveCount(0);
  await expect(page.getByRole("article", { name: /Question from/ })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: /Waits for you/ })).toContainText("1");

  // a reload opens the same pick; the x clears it
  await page.reload();
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toBeVisible();
  await page.getByRole("button", { name: "Clear the filter" }).click();
  await expect(page).not.toHaveURL(/project=/);
  await expect(page.getByRole("region", { name: "Done" })).toBeVisible();

  // keys: 1 is Runs; j then Enter opens a row's panel; Esc closes it; / focuses the search
  await page.keyboard.press("1");
  await page.keyboard.press("j");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.keyboard.press("2");
  await page.keyboard.press("/");
  await expect(page.getByRole("searchbox")).toBeFocused();
});

test("Cmd-K jumps to a map or a ticket", async ({ page }) => {
  await page.goto("/next/");
  await expect(page.getByRole("list", { name: "Running now" })).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByRole("option", { name: "other/site", exact: true }).click();
  await expect(page).toHaveURL(/map=other%2Fsite/);
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByRole("option", { name: /Draw the header/ }).click();
  await expect(page).toHaveURL(/t=demo%2Fboard%231/);
});

test("on a phone the sidebar is a sheet behind the menu button", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/next/");
  await expect(page.getByRole("navigation", { name: "Projects and maps" })).toHaveCount(0);
  await page.getByRole("button", { name: "Projects and maps" }).click();
  const sheet = page.getByRole("dialog", { name: "Projects" });
  await sheet.getByRole("button", { name: /^other/ }).click();
  await expect(sheet).toHaveCount(0);
  await expect(page).toHaveURL(/project=other/);
  await expect(page.getByRole("list", { name: "Running now" }).getByRole("listitem")).toHaveCount(1);
});

test("History lists every run by day, filters them, opens one beside the list and steps through its pictures", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/next/");
  await page.keyboard.press("5");
  await expect(page.getByRole("tab", { name: "History" })).toHaveAttribute("aria-selected", "true");
  const list = page.getByRole("main");
  // 7 days is the default range: the 20-day-old run is not there
  await expect(list.getByRole("button", { name: "Show who runs what" })).toBeVisible();
  await expect(list.getByRole("button", { name: "Wire up the very first sketch" })).toHaveCount(0);
  await page.getByRole("group", { name: "Time range" }).getByRole("button", { name: "30 days" }).click();
  await expect(list.getByRole("button", { name: "Wire up the very first sketch" })).toBeVisible();
  await page.getByRole("group", { name: "Time range" }).getByRole("button", { name: "7 days" }).click();
  // chips and search
  await page.getByRole("group", { name: "Outcome" }).getByRole("button", { name: "failed" }).click();
  await expect(list.getByRole("button", { name: "Fix the sheet's focus" })).toBeVisible();
  await expect(list.getByRole("button", { name: "Show who runs what" })).toHaveCount(0);
  await expect(page).toHaveURL(/out=failed/);
  await page.getByRole("group", { name: "Outcome" }).getByRole("button", { name: "failed" }).click();
  await page.getByRole("button", { name: "Has pictures" }).click();
  await expect(list.getByRole("button", { name: "Drag a ticket into the queue" })).toBeVisible();
  await expect(list.getByRole("button", { name: "Fix the sheet's focus" })).toHaveCount(0);
  await page.getByRole("button", { name: "Has pictures" }).click();
  await page.getByRole("searchbox", { name: "Search runs" }).fill("fonts");
  await expect(list.getByRole("button", { name: /Pick the shop/ })).toBeVisible();
  await expect(list.getByRole("button", { name: "Show who runs what" })).toHaveCount(0);
  await page.getByRole("searchbox", { name: "Search runs" }).fill("");
  // a run opens beside the list, in its own page link
  await list.getByRole("button", { name: "Show who runs what" }).click();
  await expect(page).toHaveURL(/run=demo%2Fboard%237/);
  const run = page.getByRole("region", { name: "Run" });
  await expect(run.getByRole("heading", { name: "Show who runs what" })).toBeVisible();
  await expect(list.getByRole("button", { name: "Fix the sheet's focus" })).toBeVisible();
  await expect(run).toContainText("sonnet");
  await expect(run.getByRole("link", { name: "Report in Obsidian" })).toHaveAttribute("href", /^obsidian:/);
  await expect(run.getByRole("link", { name: "Ticket" })).toHaveAttribute("href", /^obsidian:/);
  await run.getByRole("tab", { name: /Checks/ }).click();
  await expect(run.getByRole("list", { name: "Checks" })).toContainText("pnpm typecheck");
  await run.getByRole("tab", { name: "Report" }).click();
  await expect(run.getByRole("heading", { name: "What changed" })).toBeVisible();
  await run.getByRole("tab", { name: "Log" }).click();
  await run.getByRole("searchbox", { name: "Search the log" }).fill("Edit");
  await expect(run.locator("pre[aria-label=Log]")).toHaveText("→ Edit src/Header.tsx");
  // the picture viewer: arrows, keys, zoom, Esc
  await run.getByRole("tab", { name: /Pictures/ }).click();
  await run.getByRole("button", { name: "Open board-1440.png" }).click();
  const viewer = page.getByRole("dialog", { name: /^Picture \d+ of \d+/ });
  await expect(page).toHaveURL(/pic=board-1440\.png/);
  await expect(viewer.getByRole("img", { name: "board-1440.png" })).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(viewer.getByRole("img", { name: "board-phone.png" })).toBeVisible();
  await viewer.getByRole("button", { name: "Next picture" }).click();
  await expect(viewer.getByRole("img", { name: "sheet-open.png" })).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(viewer.getByRole("img", { name: "board-1440.png" })).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await expect(viewer.getByRole("img", { name: "sheet-open.png" })).toBeVisible();
  await page.keyboard.press("+");
  await expect(viewer).toContainText("125%");
  await viewer.getByRole("img", { name: "sheet-open.png" }).hover();
  await page.mouse.wheel(0, -100);
  await expect(viewer).not.toContainText("125%");
  await viewer.getByRole("button", { name: "Show board-phone.png" }).click();
  await expect(viewer.getByRole("img", { name: "board-phone.png" })).toBeVisible();
  await expect(viewer).toContainText("100%");
  await page.keyboard.press("Escape");
  await expect(viewer).toHaveCount(0);
  await expect(page).not.toHaveURL(/pic=/);
  expect(errors).toEqual([]);
  // a reload on the run's link opens the same run
  await page.reload();
  await expect(page.getByRole("region", { name: "Run" }).getByRole("heading", { name: "Show who runs what" })).toBeVisible();
});

test("History: the sidebar's project applies, and on a phone a run takes the page", async ({ page }) => {
  await page.goto("/next/?view=history&project=other");
  const list = page.getByRole("main");
  await expect(list.getByRole("button", { name: /Pick the shop/ })).toBeVisible();
  await expect(list.getByRole("button", { name: "Show who runs what" })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/next/?view=history");
  await page.getByRole("main").getByRole("button", { name: "Show who runs what" }).click();
  await expect(page.getByRole("region", { name: "Run" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Fix the sheet's focus" })).toBeHidden();
  await page.getByRole("button", { name: "Back to the list" }).click();
  await expect(page.getByRole("button", { name: "Fix the sheet's focus" })).toBeVisible();
});

/** Screenshots for the report: SB_SHOTS=<folder> writes them; without it this test does nothing. */
test("screenshots of History", async ({ page }) => {
  const dir = process.env.SB_SHOTS;
  test.skip(dir === undefined, "SB_SHOTS names the folder to write to");
  const to = (n: string): string => `${dir ?? ""}/${n}`;
  await page.goto("/next/?view=history&run=demo%2Fboard%237");
  await expect(page.getByRole("region", { name: "Run" })).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: to("history-1440.png") });
  await page.getByRole("button", { name: "Open board-1440.png" }).click();
  await expect(page.getByRole("dialog", { name: /^Picture \d+ of \d+/ }).getByRole("img", { name: "board-1440.png" })).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: to("viewer-1440.png") });
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/next/?view=history");
  await expect(page.getByRole("button", { name: "Show who runs what" })).toBeVisible();
  await page.screenshot({ path: to("history-phone.png") });
  await page.goto("/next/?view=history&run=demo%2Fboard%237&pic=board-phone.png");
  await expect(page.getByRole("dialog", { name: /^Picture \d+ of \d+/ }).getByRole("img", { name: "board-phone.png" })).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: to("viewer-phone.png") });
});

test("screenshots of Waits for you", async ({ page }) => {
  const dir = process.env.SB_SHOTS;
  test.skip(dir === undefined, "SB_SHOTS names the folder to write to");
  const to = (n: string): string => `${dir ?? ""}/${n}`;
  await page.goto("/next/?view=waits");
  await expect(page.getByRole("button", { name: "Mark all seen" })).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: to("waits-before.png") });
  await page.getByRole("button", { name: "Mark all seen" }).click();
  await expect(page.getByRole("region", { name: "Failed" })).toHaveCount(0);
  await page.waitForTimeout(300);
  await page.screenshot({ path: to("waits-after.png") });
});

for (const [view, scheme] of [["runs", "light"], ["queue", "dark"], ["waits", "light"], ["waits", "dark"], ["history", "light"], ["history", "dark"], ["sessions", "light"], ["sessions", "dark"]] as const) {
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

test("Sessions: one card per live session with its map, flags, and a Sheet with the feed", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/next/");
  await page.keyboard.press("4");
  await expect(page.getByRole("tab", { name: /Sessions/ })).toHaveAttribute("aria-selected", "true");
  const cards = page.getByRole("list", { name: "Live sessions" }).getByRole("listitem");
  // three workers and the owner's chat
  await expect(cards).toHaveCount(4);
  await expect(cards.first().getByRole("img", { name: "What the session is doing, as a map" }).locator("svg")).toBeVisible();
  // a failure shows the red dot; a session silent 5+ minutes wears the amber ring
  const failing = cards.filter({ hasText: "Run the board against the real hub" });
  await expect(failing.getByRole("img", { name: "a failure in the last 5 minutes" })).toBeVisible();
  await expect(cards.filter({ hasText: "Read the accounts' usage" })).toHaveClass(/ring-warn/);
  await expect(cards.filter({ hasText: "Write the shop's copy" }).getByRole("img", { name: /failure/ })).toHaveCount(0);
  // project and account on the card
  await expect(failing).toContainText("demo · main");
  // the filter
  await page.getByRole("button", { name: /^Chats/ }).click();
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("Charting the board");
  await page.getByRole("button", { name: /^All/ }).click();
  // a card opens the Sheet: the big map and the last actions
  await failing.getByRole("button", { name: "What the session is doing, as a map" }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByRole("img", { name: "What the session is doing, as a map" }).locator("svg")).toBeVisible();
  const feed = sheet.getByRole("list", { name: "Last actions" });
  await expect(feed.getByRole("listitem")).toHaveCount(5);
  await expect(feed.getByRole("listitem").first()).toContainText("pnpm test");
  await expect(feed.getByRole("img", { name: "failed" })).toHaveCount(1);
  await expect(sheet).toContainText("context 72%");
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("screenshots of Sessions", async ({ page }) => {
  const dir = process.env.SB_SHOTS;
  test.skip(dir === undefined, "SB_SHOTS names the folder to write to");
  const to = (n: string): string => `${dir ?? ""}/${n}`;
  const shoot = async (scheme: "light" | "dark", name: string, sheet: boolean): Promise<void> => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto(sheet ? "/next/?view=sessions&sess=demo%2Fboard%235" : "/next/?view=sessions");
    if (sheet) await expect(page.getByRole("dialog").getByRole("list", { name: "Last actions" })).toBeVisible();
    else await expect(page.getByRole("list", { name: "Live sessions" }).getByRole("listitem")).toHaveCount(4);
    await page.waitForTimeout(600);
    await page.screenshot({ path: to(name) });
  };
  await shoot("light", "sessions-1440.png", false);
  await shoot("dark", "sessions-dark-1440.png", false);
  await shoot("light", "sessions-sheet-1440.png", true);
  await page.setViewportSize({ width: 390, height: 800 });
  await shoot("light", "sessions-phone.png", false);
  await shoot("dark", "sessions-sheet-phone.png", true);
});

test("screenshots of a check that could not run", async ({ page }) => {
  const dir = process.env.SB_SHOTS;
  test.skip(dir === undefined, "SB_SHOTS names the folder to write to");
  const to = (n: string): string => `${dir ?? ""}/${n}`;
  await page.route("**/api/state", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as { queue: { items: Record<string, unknown>[] } };
    const t = Date.now() / 1000;
    const failed = body.queue.items.find((i) => i.key === "demo/board#6");
    body.queue.items.push({
      links: failed?.links,
      key: "demo/board#2", kind: "ticket", agent: null, state: "recheck", tries: 1, started: t - 1800, ended: t - 600,
      commit: "fedcba9876543210", rechecks: 1, recheck_at: t + 600, run: "/vault/runs/2026-11-13-board", log: "/vault/runs/2026-11-13-board/2.log",
      note: "check could not run: pnpm test exited 75 (the tool it needs did not answer); rechecking in 10 minutes (1 of 6)",
      checks: [{ cmd: "pnpm test", code: 75, secs: 300, tail: "Unity Editor did not answer" }],
    });
    await route.fulfill({ response: res, json: body });
  });
  await page.goto("/next/?view=runs");
  await expect(page.getByRole("list", { name: "Checks waiting to run" })).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: to("runs-recheck.png") });
  await page.goto("/next/?view=runs&t=demo%2Fboard%232");
  await expect(page.getByRole("dialog").getByText("1 of 1 check could not run")).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Queue it" })).toHaveCount(0);
  await page.getByRole("dialog").getByText("1 of 1 check could not run").click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: to("sheet-recheck.png") });
});
