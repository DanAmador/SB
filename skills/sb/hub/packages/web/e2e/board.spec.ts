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

test("Run is the landing page: one row per worker run, the silent one amber, never a chat session", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/next/");
  await expect(page.getByRole("tab", { name: /^Run\b/ })).toHaveAttribute("aria-selected", "true");
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
  await expect(page.getByRole("list", { name: "Running now" }).getByText("Charting the board")).toHaveCount(0);
  // the Waits for you count is the page's alarm: a question, a failed run, a done run
  await expect(page.getByRole("tab", { name: /Waits for you/ })).toContainText("4");
  // a row opens the ticket's panel, with Message and Stop
  await busy.getByRole("button", { name: "Show details" }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByRole("link", { name: "Open in Obsidian" }).first()).toHaveAttribute("href", /^obsidian:/);
  await expect(sheet.getByRole("link", { name: "Map" })).toHaveAttribute("href", /^obsidian:/);
  await expect(sheet.getByRole("button", { name: "Message" })).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Stop" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("the panel's Stop asks why, confirms and calls the stop route; no message is sent", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/next/");
  const row = page.getByRole("list", { name: "Running now" }).getByRole("listitem").filter({ hasText: "writing the copy" });
  await row.getByRole("button", { name: "Show details" }).click();
  const sheet = page.getByRole("dialog");
  await sheet.getByRole("button", { name: "Stop" }).click();
  // no reason: it asks for one and posts nothing
  await sheet.getByRole("button", { name: "Stop…" }).click();
  await expect(sheet.getByText("Say why first.")).toBeVisible();
  await sheet.getByLabel("Why it stops").fill("it edits the wrong checkout");
  await sheet.getByRole("button", { name: "Stop…" }).click();
  await expect(sheet.getByText("Stop this worker now: “it edits the wrong checkout”?", { exact: false })).toBeVisible();
  // Cancel posts nothing
  await sheet.getByRole("button", { name: "Cancel" }).first().click();
  expect(await (await page.request.get("/api/__stops")).json()).toEqual([]);
  await sheet.getByRole("button", { name: "Stop…" }).click();
  await sheet.getByRole("button", { name: "Yes, stop it" }).click();
  await expect(sheet.getByText("Stopping, by you: it edits the wrong checkout")).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Stop", exact: true })).toHaveCount(0);
  await expect(sheet.getByRole("button", { name: "Message" })).toBeVisible();
  expect(await (await page.request.get("/api/__stops")).json()).toEqual([{ key: "other/site#3", reason: "it edits the wrong checkout" }]);
  // the old stop sentence is not sent as a message any more
  const st = (await (await page.request.get("/api/state")).json()) as { messages: Record<string, { to: string }> };
  expect(Object.values(st.messages).filter((m) => m.to === "other/site#3")).toEqual([]);
  expect(errors).toEqual([]);
});

test.describe("Run tab", () => {
  const calls = async (page: Page): Promise<{ moveMap: number; map: number }> => (await page.request.get("/api/__calls")).json() as Promise<{ moveMap: number; map: number }>;
  const order = (page: Page) => page.getByTestId("map-block").evaluateAll((els) => els.map((e) => e.getAttribute("data-map")));

  test("?view=runs and ?view=queue open the Run tab", async ({ page }) => {
    for (const v of ["runs", "queue"]) {
      await page.goto(`/next/?view=${v}`);
      await expect(page.getByRole("tab", { name: /^Run\b/ })).toHaveAttribute("aria-selected", "true");
      await expect(page.getByTestId("blocks")).toBeVisible();
    }
    await expect(page.getByRole("tab", { name: /^Queue/ })).toHaveCount(0);
  });

  test("one line for the night, a block per map in the queue's order with its counts; Running now holds only what runs", async ({ page }) => {
    await page.goto("/next/");
    await expect(page.getByTestId("night-line")).toContainText("3 running · 1 next · 1 done · 2 fell short");
    expect(await order(page)).toEqual(["demo/board", "other/site"]);
    const board = page.getByRole("region", { name: "The demo board" });
    await expect(board.getByTestId("counts")).toHaveText("1 done · 2 running · 1 next · 1 fell short");
    // blocks with something running or fallen short start open, in run order: ended, running, next
    await expect(board.locator("li[data-mark]")).toHaveCount(5);
    await expect(board.locator("li[data-mark]").first()).toHaveAttribute("data-mark", "done");
    await expect(board.locator("li[data-mark]").last()).toHaveAttribute("data-mark", "next");
    await expect(board.locator("li[data-key='demo/board#3']")).toContainText("#1");
    // Running now: exactly the three workers; a ticket nobody queued is in neither it nor the blocks
    await expect(page.getByRole("list", { name: "Running now" }).getByRole("listitem")).toHaveCount(3);
    await expect(page.getByTestId("blocks")).not.toContainText("Drag a ticket into the queue");
    await expect(page.getByRole("list", { name: "Running now" })).not.toContainText("Drag a ticket into the queue");
    await expect(page.getByRole("button", { name: /Unqueue this map: The demo board/ })).toBeVisible();
  });

  test("moving a map up calls the route and moves its block", async ({ page }) => {
    await page.goto("/next/");
    const before = await calls(page);
    await page.getByRole("button", { name: "Move The shop site up" }).click();
    await expect.poll(async () => order(page)).toEqual(["other/site", "demo/board"]);
    expect((await calls(page)).moveMap).toBe(before.moveMap + 1);
    await expect(page.getByRole("button", { name: "Move The shop site up" })).toBeDisabled();
    await page.getByRole("button", { name: "Move The shop site down" }).click();
    await expect.poll(async () => order(page)).toEqual(["demo/board", "other/site"]);
  });

  test("at 375 px the tab is one column and nothing scrolls sideways", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/next/");
    await expect(page.getByTestId("blocks")).toBeVisible();
    const wide = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    expect(wide).toBe(false);
  });

  test("screenshots of the Run tab", async ({ page }) => {
    const dir = process.env.SB_SHOTS;
    test.skip(dir === undefined, "SB_SHOTS names the folder to write to");
    const to = (n: string): string => `${dir ?? ""}/${n}`;
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/next/");
    await expect(page.getByTestId("blocks")).toBeVisible();
    await page.waitForTimeout(300);
    await page.screenshot({ path: to("run-light.png"), fullPage: true });
    await page.emulateMedia({ colorScheme: "dark" });
    await page.waitForTimeout(300);
    await page.screenshot({ path: to("run-dark.png"), fullPage: true });
    await page.setViewportSize({ width: 375, height: 800 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: to("run-phone.png"), fullPage: true });
  });

  test("Queue on a map's row calls the route once, its block appears and the row leaves Queue a map", async ({ page }) => {
    await page.goto("/next/");
    const offer = page.getByRole("region", { name: "Queue a map" });
    const row = offer.locator("li[data-map='demo/batch']");
    await expect(row).toContainText("The batch map");
    await expect(row).toContainText("would add 5 tickets");
    await expect(page.getByRole("region", { name: "The batch map" })).toHaveCount(0);
    const before = await calls(page);
    await row.getByRole("button", { name: "Queue The batch map" }).click();
    await expect(page.getByRole("status")).toContainText("Queued 5 tickets of The batch map");
    await expect(page.getByRole("region", { name: "The batch map" }).getByTestId("counts")).toHaveText("5 next");
    await expect(offer.locator("li[data-map='demo/batch']")).toHaveCount(0);
    expect((await calls(page)).map).toBe(before.map + 1);
    // put the fixture back for the tests after this one
    await page.request.post("/api/queue/set", { data: { keys: ["demo/board#3"], version: null } });
  });
});

test("the table's filters live in the page link; the panel opens as a sheet; one tick and Queue queues", async ({ page }) => {
  await page.goto("/next/?view=queue&q=header");
  const found = page.getByTestId("ticket-rows");
  // the title opens the ticket in Obsidian
  await expect(found.getByRole("link", { name: "Draw the header", exact: true })).toHaveAttribute("href", "obsidian://open?path=%2Fvault%2Fdemo%2Fboard%2Fissues%2F1.md");
  await page.getByRole("button", { name: /^can run now/ }).click();
  await expect(page).toHaveURL(/ts=can\+run\+now/);
  await expect(found.getByRole("row")).toHaveCount(1);
  await page.getByRole("button", { name: /^can run now/ }).click();
  await expect(page).not.toHaveURL(/ts=/);
  await found.getByRole("button", { name: "Show details" }).click();
  await expect(page).toHaveURL(/t=demo%2Fboard%231/);
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByRole("heading", { name: "Draw the header" })).toBeVisible();
  // a digest: Open in Obsidian first, no ticket body of its own
  await expect(sheet.getByRole("navigation", { name: "In Obsidian" }).getByRole("link").first()).toHaveText("Open in Obsidian");
  await expect(sheet.getByText("Not this ticket")).toHaveCount(0); // the three steering words are shown (Steer), the ticket body is not
  await expect(sheet.getByRole("button", { name: "Queue it" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await expect(page).not.toHaveURL(/t=/);
  await found.getByRole("checkbox", { name: "Tick Draw the header" }).check();
  await page.getByTestId("selection-bar").getByRole("button", { name: /^Queue 1/ }).click();
  await expect(page.getByRole("region", { name: "The demo board" }).getByText("Draw the header")).toBeVisible();
  // queued, so no longer ticked: the bar is gone
  await expect(page.getByTestId("selection-bar")).toHaveCount(0);
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
  await expect(shop.getByLabel("1 can run now")).toBeVisible();
  await expect(shop.getByLabel("1 queued")).toBeVisible();
  await expect(shop.getByRole("img", { name: "running" })).toBeVisible();
  await expect(side.getByText("can run · queued")).toBeVisible();
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
  await expect(page.getByRole("tab", { name: /^Run\b/ })).toContainText("1");

  // the search under the blocks finds only this map's open tickets; no block of the other map
  const found = page.getByTestId("ticket-rows");
  await expect(found.getByRole("row")).toHaveCount(3);
  await expect(found).toContainText("Draw the shop window");
  await expect(found).not.toContainText("Draw the header");
  await expect(page.getByTestId("blocks")).not.toContainText("Show the queue in order");

  // Waits for you: the shop's failed run only, no question, no done run
  await page.keyboard.press("2");
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
  await page.keyboard.press("1");
  await page.keyboard.press("/");
  await expect(page.getByRole("searchbox")).toBeFocused();
});

test("Active only leaves the projects and maps with something running or queued, and survives a reload", async ({ page }) => {
  await page.goto("/next/");
  const side = page.getByRole("navigation", { name: "Projects and maps" });
  const sw = side.getByRole("switch", { name: "Active only" });
  await expect(sw).toHaveAttribute("aria-checked", "false");
  await expect(side.getByRole("button", { name: "1 quiet map" })).toBeVisible();
  await sw.click();
  await expect(page).toHaveURL(/act=1/);
  await expect(sw).toHaveAttribute("aria-checked", "true");
  await expect(side.getByRole("button", { name: /quiet map/ })).toHaveCount(0);
  await expect(side.getByRole("button", { name: /^board / })).toBeVisible();
  await page.reload();
  await expect(side.getByRole("switch", { name: "Active only" })).toHaveAttribute("aria-checked", "true");
  await side.getByRole("switch", { name: "Active only" }).click();
  await expect(page).not.toHaveURL(/act=/);
  await expect(side.getByRole("button", { name: "1 quiet map" })).toBeVisible();
});

test("quiet maps fold under one line that opens; a picked quiet map stays shown after a reload", async ({ page }) => {
  await page.goto("/next/");
  const side = page.getByRole("navigation", { name: "Projects and maps" });
  await expect(side.getByRole("button", { name: /^site/ })).toBeVisible();
  await expect(side.getByRole("button", { name: /^old/ })).toHaveCount(0);
  const fold = side.getByRole("button", { name: "1 quiet map" });
  await expect(fold).toHaveAttribute("aria-expanded", "false");
  await fold.click();
  await expect(fold).toHaveAttribute("aria-expanded", "true");
  await side.getByRole("button", { name: /^old/ }).click();
  await expect(page).toHaveURL(/map=other%2Fold/);
  await page.reload();
  await expect(side.getByRole("button", { name: /^old/ })).toHaveAttribute("aria-current", "page");
  // picked, so it is shown and the fold line is gone
  await expect(side.getByRole("button", { name: /quiet map/ })).toHaveCount(0);
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
  await page.keyboard.press("3");
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
  const run = page.getByRole("region", { name: /^Run\b/ });
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
  await expect(page.getByRole("region", { name: /^Run\b/ }).getByRole("heading", { name: "Show who runs what" })).toBeVisible();
});

test("History: the sidebar's project applies, and on a phone a run takes the page", async ({ page }) => {
  await page.goto("/next/?view=history&project=other");
  const list = page.getByRole("main");
  await expect(list.getByRole("button", { name: /Pick the shop/ })).toBeVisible();
  await expect(list.getByRole("button", { name: "Show who runs what" })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/next/?view=history");
  await page.getByRole("main").getByRole("button", { name: "Show who runs what" }).click();
  await expect(page.getByRole("region", { name: /^Run\b/ })).toBeVisible();
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
  await expect(page.getByRole("region", { name: /^Run\b/ })).toBeVisible();
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

for (const [view, scheme] of [["run", "light"], ["run", "dark"], ["waits", "light"], ["waits", "dark"], ["history", "light"], ["history", "dark"]] as const) {
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

test.describe("Run tab: who is on each ticket", () => {
  test("the head names the session in charge, a row with a worker opens its panel, Helpers and Other chats", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/next/");
    await expect(page.getByRole("tab", { name: /Sessions/ })).toHaveCount(0);
    const demo = page.locator("[data-testid=map-block][data-map='demo/board']");
    await expect(demo.getByTestId("in-charge")).toContainText("Charting the board");
    await expect(page.locator("[data-testid=map-block][data-map='other/site']").getByTestId("in-charge")).toContainText("run by the queue");
    const row = demo.locator("li[data-key='demo/board#5']");
    await expect(row).toHaveAttribute("data-worker", "live");
    await row.getByRole("button", { name: /^Open the worker on/ }).click();
    const sheet = page.getByRole("dialog");
    await expect(sheet.getByRole("img", { name: "What the session is doing, as a map" }).locator("svg")).toBeVisible();
    const feed = sheet.getByRole("list", { name: "Last actions" });
    await expect(feed.getByRole("listitem")).toHaveCount(5);
    await expect(feed.getByRole("img", { name: "failed" })).toHaveCount(1);
    await expect(sheet).toContainText("context 72%");
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    // helpers, folded
    const helpers = demo.getByTestId("helpers");
    await expect(helpers).not.toHaveAttribute("open", "");
    await helpers.locator("summary").click();
    await helpers.getByRole("button", { name: /Scout the tests/ }).click();
    await expect(page.getByRole("dialog")).toContainText("Scout the tests");
    await page.keyboard.press("Escape");
    const other = page.getByTestId("other-chats");
    await expect(other).toContainText("1 live");
    await expect(other).toContainText("Reading the old notes");
    await expect(other).toContainText("Helpers (1)");
    // the tab counts running workers
    await expect(page.getByRole("tab", { name: /^Run/ })).toContainText("3");
    expect(errors).toEqual([]);
  });

  test("a silent worker's row carries the silent mark", async ({ page }) => {
    await page.goto("/next/");
    const row = page.locator("li[data-key='demo/board#8']");
    await expect(row).toHaveAttribute("data-worker", "silent");
    await expect(row.getByTestId("silent")).toBeVisible();
    await expect(page.locator("li[data-key='demo/board#5']").getByTestId("silent")).toHaveCount(0);
  });

  test("?view=sessions and a sess link land on the Run tab with the panel open", async ({ page }) => {
    await page.goto("/next/?view=sessions");
    await expect(page.getByRole("tab", { selected: true })).toContainText("Run");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.goto("/next/?view=sessions&sess=demo%2Fboard%235");
    // the panel is modal: the tabs behind it are hidden from the accessibility tree until it closes
    await expect(page.getByRole("dialog").getByRole("list", { name: "Last actions" })).toBeVisible();
    await expect(page.getByRole("tab", { selected: true, includeHidden: true })).toContainText("Run");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("tab", { selected: true })).toContainText("Run");
  });

  test("at 375 px nothing scrolls sideways", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/next/");
    await expect(page.getByTestId("other-chats")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });

  test("screenshots of who is on each ticket", async ({ page }) => {
    const dir = process.env.SB_SHOTS;
    test.skip(dir === undefined, "SB_SHOTS names the folder to write to");
    const to = (n: string): string => `${dir ?? ""}/${n}`;
    const shoot = async (scheme: "light" | "dark", name: string, sheet: boolean): Promise<void> => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(sheet ? "/next/?sess=demo%2Fboard%235" : "/next/");
      if (sheet) await expect(page.getByRole("dialog").getByRole("list", { name: "Last actions" })).toBeVisible();
      else await page.locator("[data-testid=helpers] summary").click();
      await expect(page.getByTestId("other-chats")).toBeVisible();
      await page.waitForTimeout(600);
      await page.screenshot({ path: to(name) });
    };
    await shoot("light", "run-who-1440.png", false);
    await shoot("dark", "run-who-dark-1440.png", false);
    await shoot("light", "run-panel-1440.png", true);
    await page.setViewportSize({ width: 375, height: 800 });
    await shoot("light", "run-who-375.png", false);
    await shoot("dark", "run-panel-375.png", true);
  });
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
  await expect(page.locator("li[data-mark=recheck]")).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: to("runs-recheck.png") });
  await page.goto("/next/?view=runs&t=demo%2Fboard%232");
  await expect(page.getByRole("dialog").getByText("1 of 1 check could not run")).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Queue it" })).toHaveCount(0);
  await page.getByRole("dialog").getByText("1 of 1 check could not run").click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: to("sheet-recheck.png") });
});

test("screenshots of the sidebar", async ({ page }) => {
  const dir = process.env.SB_SHOTS;
  test.skip(dir === undefined, "SB_SHOTS names the folder to write to");
  const to = (n: string): string => `${dir ?? ""}/${n}`;
  // a map whose tickets cannot run only for want of checks, so the mark shows
  await page.route("**/api/tickets", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as Record<string, unknown>[];
    const first = body[0] ?? {};
    body.push({ ...first, map: "other/bare", num: 1, map_title: "bare", checks: [], state: "not ready", reason: "no check commands", file: "/vault/other/bare/issues/1.md" });
    await route.fulfill({ response: res, json: body });
  });
  await page.goto("/next/");
  const side = page.getByRole("navigation", { name: "Projects and maps" });
  await side.getByRole("button", { name: /quiet map/ }).first().click();
  await expect(side.getByText("no checks")).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: to("sidebar-1440.png") });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.waitForTimeout(300);
  await page.screenshot({ path: to("sidebar-dark-1440.png") });
  await page.emulateMedia({ colorScheme: "light" });
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/next/");
  await page.getByRole("button", { name: "Projects and maps" }).click();
  const sheet = page.getByRole("dialog", { name: "Projects" });
  await sheet.getByRole("button", { name: /quiet map/ }).first().click();
  await expect(sheet.getByText("no checks")).toBeVisible();
  // the sheet itself does not scroll sideways
  expect(await sheet.evaluate((e) => e.scrollWidth <= e.clientWidth)).toBe(true);
  await page.waitForTimeout(400);
  await page.screenshot({ path: to("sidebar-375.png") });
});

test.describe("Map view", () => {
  test("picking a map draws one node per ticket and an arrow per after; a node opens its panel; the legend names the states", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/next/");
    await page.getByRole("navigation", { name: "Projects and maps" }).getByRole("button", { name: /^board / }).click();
    const graph = page.getByTestId("map-graph");
    await expect(graph.locator(".react-flow__node")).toHaveCount(8 + 1);
    await expect(graph.locator(".react-flow__edge")).toHaveCount(6);
    await expect(page.getByRole("list", { name: "Legend" }).getByRole("listitem")).toHaveCount(9);
    // the queued one shows its place; the other map's blocker is named by its map
    await expect(graph.getByRole("button", { name: /Show the queue in order\s*3 · Queued\s*next 1/ })).toBeVisible();
    await expect(graph.getByRole("button", { name: /other\/site/ })).toBeVisible();
    // keyboard: Tab reaches a node, Enter opens its panel
    const node = graph.getByRole("button", { name: /^Drag a ticket into the queue 2 / });
    await node.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page).toHaveURL(/t=demo%2Fboard%232/);
    await page.keyboard.press("Escape");
    await graph.getByRole("button", { name: /^Decide the colour scheme 4 / }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("the legend counts each state; a pressed chip dims the boxes of every other state and lives in the page link", async ({ page }) => {
    await page.goto("/next/?project=demo&map=demo%2Fboard");
    const graph = page.getByTestId("map-graph");
    const legend = page.getByRole("list", { name: "Legend" });
    const queued = legend.getByRole("button", { name: /^Queued/ });
    await expect(queued).toContainText("1");
    const box = graph.getByRole("button", { name: /Show the queue in order/ });
    const other = graph.getByRole("button", { name: /^Drag a ticket into the queue 2 / });
    await expect(other).not.toHaveClass(/opacity-25/);
    // each state reads in words: running, a place in line, and not queued
    await expect(other).toContainText("2 · Running");
    await expect(box).toContainText("next 1");
    await expect(graph.getByRole("button", { name: /· Not queued/ }).first()).toBeVisible();
    await expect(graph.getByRole("button", { name: "Show running" })).toBeVisible();
    await queued.click();
    await expect(page).toHaveURL(/ms=queued/);
    await expect(queued).toHaveAttribute("aria-pressed", "true");
    await expect(box).not.toHaveClass(/opacity-25/);
    await expect(other).toHaveClass(/opacity-25/);
    await page.reload();
    await expect(graph.getByRole("button", { name: /^Drag a ticket into the queue 2 / })).toHaveClass(/opacity-25/);
    await legend.getByRole("button", { name: /^Queued/ }).click();
    await expect(page).not.toHaveURL(/ms=/);
    await expect(graph.getByRole("button", { name: /^Drag a ticket into the queue 2 / })).not.toHaveClass(/opacity-25/);
  });

  test("a box dragged over three nodes ticks them; the bar says 3, Queue queues those three, Table shows them ticked; Escape clears", async ({ page }) => {
    const before = await queuedKeys(page);
    await page.goto("/next/?project=demo&map=demo%2Fbatch");
    const graph = page.getByTestId("map-graph");
    await expect(graph.locator(".react-flow__node")).toHaveCount(5);
    await page.waitForTimeout(500);
    const rect = async (name: string) => {
      const b = await graph.getByRole("button", { name: new RegExp(`^${name} `) }).boundingBox();
      if (b === null) throw new Error(`${name} is not on screen`);
      return b;
    };
    const [a, c, d] = [await rect("Batch A"), await rect("Batch C"), await rect("Batch D")];
    const area = await graph.boundingBox();
    if (area === null) throw new Error("the graph is not on screen");
    // from the empty corner above the first row to the middle of the last box of that row: A, B and C only
    await page.mouse.move(area.x + 4, a.y - 6);
    await page.mouse.down();
    await page.mouse.move(c.x + c.width / 2, a.y + a.height / 2, { steps: 8 });
    await page.mouse.up();
    const bar = page.getByTestId("selection-bar");
    await expect(bar).toBeVisible();
    await expect(bar).toContainText("3");
    await expect(graph.getByText("Ticked")).toHaveCount(3);
    expect(d.y).toBeGreaterThan(a.y + a.height);
    const shots = process.env.SB_SHOTS;
    if (shots !== undefined) await page.screenshot({ path: `${shots}/box-ticked-light.png`, fullPage: true });
    // Shift-click ticks a fourth, a second one unticks it
    await graph.getByRole("button", { name: /^Batch D / }).click({ modifiers: ["Shift"] });
    await expect(graph.getByText("Ticked")).toHaveCount(4);
    await graph.getByRole("button", { name: /^Batch D / }).click({ modifiers: ["Shift"] });
    await expect(graph.getByText("Ticked")).toHaveCount(3);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    if (shots !== undefined) {
      await page.emulateMedia({ colorScheme: "dark" });
      await page.reload();
      await expect(graph.getByText("Ticked")).toHaveCount(0);
      await page.mouse.move(area.x + 4, a.y - 6);
      await page.mouse.down();
      await page.mouse.move(c.x + c.width / 2, a.y + a.height / 2, { steps: 8 });
      await page.mouse.up();
      await expect(graph.getByText("Ticked")).toHaveCount(3);
      await page.screenshot({ path: `${shots}/box-ticked-dark.png`, fullPage: true });
    }
    // Table keeps the three ticked
    await page.getByRole("radio", { name: "Table" }).click();
    const rows = page.getByTestId("ticket-rows");
    await expect(rows.getByRole("checkbox", { checked: true })).toHaveCount(3);
    for (const l of ["A", "B", "C"]) await expect(rows.getByRole("checkbox", { name: `Tick Batch ${l}` })).toBeChecked();
    await page.getByRole("radio", { name: "Graph" }).click();
    await expect(graph.getByText("Ticked")).toHaveCount(3);
    // Escape clears
    await page.keyboard.press("Escape");
    await expect(bar).toHaveCount(0);
    await expect(graph.getByText("Ticked")).toHaveCount(0);
    // the node menu
    await graph.getByRole("button", { name: /^Batch E / }).click({ button: "right" });
    await page.getByRole("menuitem", { name: "Tick everything this comes after" }).click();
    await expect(graph.getByText("Ticked")).toHaveCount(3);
    await page.keyboard.press("Escape");
    await graph.getByRole("button", { name: /^Batch D / }).click({ button: "right" });
    if (shots !== undefined) await page.screenshot({ path: `${shots}/node-menu.png` });
    await page.getByRole("menuitem", { name: "Tick everything that comes after this" }).click();
    await expect(graph.getByText("Ticked")).toHaveCount(2);
    await page.keyboard.press("Escape");
    // queue three by a box again
    await page.mouse.move(area.x + 4, a.y - 6);
    await page.mouse.down();
    await page.mouse.move(c.x + c.width / 2, a.y + a.height / 2, { steps: 8 });
    await page.mouse.up();
    await bar.getByRole("button", { name: /^Queue 3/ }).click();
    await expect.poll(() => queuedKeys(page)).toEqual([...before, "demo/batch#1", "demo/batch#2", "demo/batch#3"]);
    await expect(bar).toHaveCount(0);
    await page.request.post("/api/queue/set", { data: { keys: before, version: null } });
  });

  test("at 375 px a plain list shows instead of the graph, and nothing scrolls sideways", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/next/?project=demo&map=demo%2Fboard");
    const list = page.getByRole("list", { name: "Tickets of the map" });
    await expect(list.getByRole("listitem")).toHaveCount(8);
    await expect(page.getByTestId("map-graph")).toHaveCount(0);
    await expect(list.getByRole("listitem").nth(2)).toContainText("next 1");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await list.getByRole("button", { name: /Show the queue in order/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`axe finds no serious or critical issue on a map (${scheme}); screenshot`, async ({ page }) => {
      const { default: AxeBuilder } = await import("@axe-core/playwright");
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("/next/?project=demo&map=demo%2Fboard");
      await expect(page.getByTestId("map-graph").locator(".react-flow__node")).toHaveCount(9);
      await page.waitForTimeout(800);
      const dir = process.env.SB_SHOTS;
      if (dir !== undefined) await page.screenshot({ path: `${dir}/map-${scheme}-1440.png` });
      const r = await new AxeBuilder({ page }).analyze();
      const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
    });
  }
});

test.describe("Map head", () => {
  const bare = "/next/?project=demo&map=demo%2Fbare";
  test("a map without checks shows the warning and no Queue this map; setting checks removes the warning; Queue this map queues what can run", async ({ page }) => {
    await page.goto(bare);
    const head = page.getByTestId("map-head");
    await expect(head.getByRole("heading", { name: "The bare map" })).toBeVisible();
    await expect(head.getByText("Four tickets and no checks yet.")).toBeVisible();
    await expect(head.getByText("No checks: nothing here can be queued")).toBeVisible();
    await expect(head.getByRole("button", { name: "Queue this map" })).toHaveCount(0);
    await expect(page.getByTestId("map-counts")).toHaveText("1 stuck · 1 need a decision · 2 without checks");
    const dir = process.env.SB_SHOTS;
    if (dir !== undefined) {
      await page.screenshot({ path: `${dir}/maphead-1440-nochecks.png` });
      await page.setViewportSize({ width: 375, height: 800 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.screenshot({ path: `${dir}/maphead-375-nochecks.png` });
      await page.setViewportSize({ width: 1440, height: 900 });
    }
    // set the checks: the warning goes, the button comes
    await head.getByRole("button", { name: "Set them" }).click();
    await head.getByLabel("Checks of this map, separated by ;").fill("pnpm test; pnpm lint");
    await head.getByRole("button", { name: "Save checks" }).click();
    await expect(head.getByText("No checks: nothing here can be queued")).toHaveCount(0);
    await expect(page.getByTestId("map-counts")).toHaveText("2 can run · 1 stuck · 1 need a decision");
    await expect(head.getByText("Checks (2)")).toBeVisible();
    // queue the whole map: the third, after the first, is in line too
    const before = (await queuedKeys(page)).length;
    await head.getByRole("button", { name: "Queue this map" }).click();
    await expect(page.getByTestId("map-queued")).toHaveText("Queued 3 tickets; left 1 ticket: needs your decision.");
    await expect(page.getByTestId("map-counts")).toHaveText("3 queued · 1 need a decision");
    expect((await queuedKeys(page)).length).toBe(before + 3);
    expect(await queuedKeys(page)).toEqual(expect.arrayContaining(["demo/bare#1", "demo/bare#2", "demo/bare#3"]));
    await expect(head.getByRole("button", { name: "Queue this map" })).toBeDisabled();
  });

  test("the head holds at 375 px and in dark: one column, nothing scrolls sideways; screenshots", async ({ page }) => {
    const dir = process.env.SB_SHOTS;
    await page.goto("/next/?project=demo&map=demo%2Fboard");
    await expect(page.getByTestId("map-head")).toBeVisible();
    await expect(page.getByTestId("map-counts")).toHaveText("1 done · 1 running · 1 queued · 1 can run · 2 stuck · 1 need a decision");
    await page.waitForTimeout(800);
    if (dir !== undefined) await page.screenshot({ path: `${dir}/maphead-1440.png` });
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto(bare);
    await expect(page.getByTestId("map-head")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto("/next/?project=demo&map=demo%2Fboard");
    await expect(page.getByTestId("map-head")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (dir !== undefined) await page.screenshot({ path: `${dir}/maphead-375-dark.png` });
  });
});

test.describe("Ticket table", () => {
  const rowsOf = (page: Page) => page.getByTestId("ticket-rows").getByRole("row");
  const bar = (page: Page) => page.getByTestId("selection-bar");
  const tick = (page: Page, title: string) => page.getByRole("checkbox", { name: `Tick ${title}`, exact: true });

  test("tick three tickets that can run, press Queue, and all three are queued", async ({ page }) => {
    await page.goto("/next/?view=queue&project=demo&map=demo%2Fbatch");
    await expect(rowsOf(page)).toHaveCount(5);
    await expect(bar(page)).toHaveCount(0);
    for (const l of ["A", "B", "C"]) await tick(page, `Batch ${l}`).check();
    await expect(bar(page)).toContainText("3 tickets ticked");
    await expect(bar(page).getByRole("button", { name: /^Queue 3/ })).toBeVisible();
    // nothing ticked is queued yet, so Unqueue has nothing to do
    await expect(bar(page).getByRole("button", { name: /^Unqueue 0/ })).toBeDisabled();
    await bar(page).getByRole("button", { name: /^Queue 3/ }).click();
    await expect(page.getByRole("status")).toContainText("Queued 3 tickets.");
    expect(await queuedKeys(page)).toEqual(expect.arrayContaining(["demo/batch#1", "demo/batch#2", "demo/batch#3"]));
    await expect(rowsOf(page).filter({ hasText: "Batch A" })).toContainText("queued, number");
  });

  test("tick two, Comment, and both notes carry the comment; a refusal is named by its title", async ({ page }) => {
    await page.goto("/next/?view=queue&project=demo&map=demo%2Fbatch");
    await tick(page, "Batch D").check();
    await tick(page, "Batch E").check();
    // Queue skips what is already queued: here none of the two, so it applies to both and Unqueue to none
    await bar(page).getByRole("button", { name: /^Comment 2/ }).click();
    await page.getByRole("textbox", { name: "Comment" }).fill("fail");
    await page.getByRole("button", { name: "Comment on 2 tickets" }).click();
    await expect(page.getByRole("alert").last()).toContainText("Commented on 0 of 2. Failed: Batch D (refused for the test); Batch E (refused for the test)");
    await page.getByRole("textbox", { name: "Comment" }).fill("Checked by hand");
    await page.getByRole("button", { name: "Comment on 2 tickets" }).click();
    await expect(page.getByRole("status").last()).toContainText("Commented on 2 tickets.");
    const actions = (await (await page.request.get("/api/__actions")).json()) as { action: string; key: string; text: string }[];
    expect(actions.filter((a) => a.action === "comment" && a.text === "Checked by hand").map((a) => a.key).sort()).toEqual(["demo/batch#4", "demo/batch#5"]);
    await expect(bar(page)).toHaveCount(0);
  });

  test("a button says how many it applies to and skips; Drop asks once and confirms with the count", async ({ page }) => {
    await page.goto("/next/?view=queue&project=demo&map=demo%2Fbatch");
    await tick(page, "Batch A").check(); // queued by the first test
    await tick(page, "Batch D").check();
    await expect(bar(page).getByRole("button", { name: /^Queue 1\s*skips 1/ })).toBeVisible();
    await expect(bar(page).getByRole("button", { name: /^Unqueue 1\s*skips 1/ })).toBeVisible();
    await expect(bar(page).getByRole("button", { name: /^Drop 1\s*skips 1/ })).toBeVisible();
    await bar(page).getByRole("button", { name: /^Drop/ }).click();
    await page.getByRole("textbox", { name: "Reason for dropping" }).fill("Not needed");
    await page.getByRole("button", { name: "Drop 1 ticket", exact: true }).click();
    await expect(page.getByRole("status").last()).toContainText("Dropped 1 ticket, skipped 1.");
    const actions = (await (await page.request.get("/api/__actions")).json()) as { action: string; key: string }[];
    expect(actions.filter((a) => a.action === "drop").map((a) => a.key)).toEqual(["demo/batch#4"]);
  });

  test("the 'can run now' chip's count is the fixture's ready count, apart from 'can run after another'", async ({ page }) => {
    const state = (await (await page.request.get("/api/state")).json()) as { queue: { items: { key: string; state: string; kind: string }[] } };
    const tickets = (await (await page.request.get("/api/tickets")).json()) as { map: string; num: number; state: string }[];
    const busy = new Set(state.queue.items.filter((i) => ["queued", "running", "done"].includes(i.state)).map((i) => i.key));
    const ready = tickets.filter((t) => t.map.startsWith("demo/") && t.state === "ready" && !busy.has(`${t.map}#${String(t.num)}`)).length;
    expect(ready).toBeGreaterThan(0);
    await page.goto("/next/?view=queue&project=demo");
    const chip = page.getByRole("group", { name: "State" }).getByRole("button", { name: /^can run now/ });
    await expect(chip).toContainText(String(ready));
    await expect(page.getByRole("group", { name: "State" }).getByRole("button", { name: /^can run after another/ })).toHaveCount(0);
    await chip.click();
    await expect(rowsOf(page)).toHaveCount(ready);
    await expect(page).toHaveURL(/ts=can\+run\+now/);
    // a sort by a column header is kept in the link too
    await page.getByRole("button", { name: "Title", exact: true }).click();
    await expect(page).toHaveURL(/sort=title/);
    const titles = await rowsOf(page).locator("td:nth-child(2) > div > a").allInnerTexts();
    expect(titles).toEqual([...titles].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase())));
  });

  test("Space ticks the focused row, Shift-click a range, the header box every row shown", async ({ page }) => {
    await page.goto("/next/?view=queue&project=demo&map=demo%2Fbatch&sort=title");
    await expect(rowsOf(page)).toHaveCount(5);
    await rowsOf(page).first().focus();
    await page.keyboard.press("Space");
    await expect(tick(page, "Batch A")).toBeChecked();
    await expect(bar(page)).toContainText("1 ticket ticked");
    await tick(page, "Batch D").click({ modifiers: ["Shift"] });
    for (const l of ["A", "B", "C", "D"]) await expect(tick(page, `Batch ${l}`)).toBeChecked();
    await expect(tick(page, "Batch E")).not.toBeChecked();
    await expect(bar(page)).toContainText("4 tickets ticked");
    await page.keyboard.press("Space");
    await page.getByRole("checkbox", { name: "Tick every ticket shown" }).check();
    await expect(bar(page)).toContainText("5 tickets ticked");
    await page.getByRole("checkbox", { name: "Tick every ticket shown" }).uncheck();
    await expect(bar(page)).toHaveCount(0);
  });

  test("a map shows Graph | Table, kept in the link, with finished tickets in the table", async ({ page }) => {
    await page.goto("/next/?project=demo&map=demo%2Fboard");
    await expect(page.getByTestId("map-graph")).toBeVisible();
    await page.getByRole("radio", { name: "Table" }).click();
    await expect(page).toHaveURL(/mv=table/);
    await expect(page.getByTestId("map-graph")).toHaveCount(0);
    await expect(rowsOf(page)).toHaveCount(8);
    await expect(rowsOf(page).filter({ hasText: "Draw the header" })).toContainText("done");
    await expect(rowsOf(page).filter({ hasText: "Show the queue in order" })).toContainText("queued");
    await page.reload();
    await expect(page.getByRole("radio", { name: "Table" })).toHaveAttribute("aria-checked", "true");
    await page.getByRole("radio", { name: "Graph" }).click();
    await expect(page.getByTestId("map-graph")).toBeVisible();
    await expect(page).not.toHaveURL(/mv=/);
  });

  test("at 375 px the table is one column and nothing scrolls sideways", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/next/?view=queue&project=demo");
    await expect(rowsOf(page).first()).toBeVisible();
    await tick(page, "Batch A").check();
    await expect(bar(page)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const dir = process.env.SB_SHOTS;
    if (dir !== undefined) await page.screenshot({ path: `${dir}/table-375.png` });
    await bar(page).getByRole("button", { name: /^Comment/ }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });

  for (const [scheme, url] of [["light", "/next/?view=queue&project=demo"], ["dark", "/next/?project=demo&map=demo%2Fboard&mv=table"]] as const) {
    test(`axe finds no serious or critical issue on the table (${scheme}); screenshot`, async ({ page }) => {
      const { default: AxeBuilder } = await import("@axe-core/playwright");
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(url);
      await expect(rowsOf(page).first()).toBeVisible();
      await tick(page, scheme === "light" ? "Batch B" : "Show the queue in order").check();
      await tick(page, scheme === "light" ? "Batch C" : "Fix the sheet's focus").check();
      await page.waitForTimeout(500);
      const dir = process.env.SB_SHOTS;
      if (dir !== undefined) await page.screenshot({ path: `${dir}/table-${scheme}-1440.png` });
      const r = await new AxeBuilder({ page }).analyze();
      const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
    });
  }
});
