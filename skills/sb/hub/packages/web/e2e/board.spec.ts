import { expect, test, type Page } from "@playwright/test";

/** Tests share one fixture hub; they run one after another, in this order. */
test.describe.configure({ mode: "serial" });

const queuedKeys = async (page: Page): Promise<string[]> => {
  const state = (await (await page.request.get("/api/state")).json()) as { queue: { items: { key: string; state: string }[] } };
  return state.queue.items.filter((i) => i.state === "queued").map((i) => i.key);
};

/** Opens one of the Run view's own tabs. */
const runTab = async (page: Page, name: "Flow" | "Now" | "Maps" | "Queue"): Promise<void> => {
  await page.getByRole("tablist", { name: "Run" }).getByRole("tab", { name: new RegExp(`^${name}`) }).click();
};

// the hub keeps the seen marks, so every test starts with none
test.beforeEach(async ({ request }) => {
  await request.post("/api/__reset-seen");
});

test("Run is the landing page: one row per worker run, the silent one amber, never a chat session", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/next/?rt=now");
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
  // 12 min when the fixture hub starts; a loaded machine can take minutes to reach this test (13 and 20 min seen)
  await expect(busy).toContainText(/(1[2-9]|[2-5]\d) min\b/);
  await expect(busy).toContainText("opus");
  await expect(busy).toContainText("try 3 of 5"); // its third try, after two failed ones
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
  await page.goto("/next/?rt=now");
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

test.describe("The run's graph", () => {
  test.beforeEach(async ({ request }) => {
    await request.post("/api/__restore");
    await request.post("/api/__job");
  });
  test.afterEach(async ({ request }) => {
    await request.post("/api/__restore");
  });
  const night = (page: Page) => page.getByTestId("night-graph");
  const box = (page: Page, name: RegExp) => night(page).getByRole("button", { name });

  test("Everything shows the run as one timeline left to right: a band per project, a chip per map, the now line and one Done box", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/next/");
    await expect(night(page)).toBeVisible();
    for (const f of ["The demo board", "The shop site", "Jobs"]) await expect(night(page).getByText(f, { exact: true })).toBeVisible();
    for (const p of ["demo", "other"]) await expect(night(page).locator(".react-flow__node-head", { hasText: p })).toBeVisible();
    await expect(night(page).locator(".react-flow__node-now")).toHaveCount(1);
    await expect(night(page).getByTestId("night-done")).toContainText("of 8 finished");
    await expect(page.getByTestId("run-counts")).toHaveText("1 done · 3 running · 1 in checks · 1 next · 2 fell short");
    await expect(night(page).locator(".react-flow__node-box")).toHaveCount(8);
    // a ticket the run never queued is not there
    await expect(night(page).getByText("Draw the shop window")).toHaveCount(0);
    await expect(night(page).getByText("Draw the header")).toHaveCount(0);
    // the queued one has its place, drawn dashed right of now; an arrow crosses from the demo board to the shop site,
    // and each project's last ticket points at Done
    await expect(box(page, /Show the queue in order.*Queued\s*next 1/)).toBeVisible();
    await expect(box(page, /Show the queue in order/)).toHaveClass(/border-dashed/);
    await expect(night(page).locator(".react-flow__edge")).toHaveCount(1 + 2);
    // the graph is the Run view's first tab
    await expect(page.getByRole("tablist", { name: "Run" }).getByRole("tab", { name: /^Flow/ })).toHaveAttribute("aria-selected", "true");
    // any box opens the ticket's panel
    await box(page, /Run the board against the real hub/).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page).toHaveURL(/t=demo%2Fboard%235/);
    await page.keyboard.press("Escape");
    // a map chip hides that map's boxes and its arrows; pressed again they come back
    const chip = night(page).getByRole("group", { name: "Maps" }).getByRole("button", { pressed: true }).filter({ hasText: "The shop site" });
    await chip.click();
    await expect(night(page).locator(".react-flow__node-box")).toHaveCount(6);
    await expect(night(page).locator(".react-flow__edge")).toHaveCount(1);
    await night(page).getByRole("group", { name: "Maps" }).getByRole("button", { pressed: false }).filter({ hasText: "The shop site" }).click();
    await expect(night(page).locator(".react-flow__node-box")).toHaveCount(8);
    expect(errors).toEqual([]);
  });

  test("picking a project leaves only its frames", async ({ page }) => {
    await page.goto("/next/?project=other");
    await expect(night(page).getByText("The shop site", { exact: true })).toBeVisible();
    await expect(night(page).getByText("The demo board", { exact: true })).toHaveCount(0);
    await expect(night(page).getByText("Jobs", { exact: true })).toHaveCount(0);
    await expect(page.getByTestId("run-counts")).toHaveText("1 running · 1 fell short");
    await page.goto("/next/?project=demo");
    await expect(night(page).getByText("The demo board", { exact: true })).toBeVisible();
    await expect(night(page).getByText("Jobs", { exact: true })).toBeVisible();
    await expect(night(page).getByText("The shop site", { exact: true })).toHaveCount(0);
  });

  test("a finished box shows its outcome and opens its report; a map chip's arrow picks the map", async ({ page }) => {
    await page.goto("/next/");
    const done = night(page).locator(".react-flow__node-box", { hasText: "Wait on the shop's fonts" });
    await expect(done).toContainText("Done");
    await expect(done.getByRole("link", { name: "Report" })).toHaveAttribute("href", /^obsidian:\/\/open\?path=/);
    await expect(night(page).locator(".react-flow__node-box", { hasText: "Fix the sheet's focus" })).toContainText("Fell short");
    await page.getByRole("button", { name: "Open the map The demo board" }).click();
    await expect(page).toHaveURL(/map=demo%2Fboard/);
    await expect(page.getByTestId("map-graph")).toBeVisible();
    await expect(night(page)).toHaveCount(0);
  });

  test("at 375 px the list is grouped by map and nothing scrolls sideways", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/next/");
    await expect(page.getByTestId("night-list").getByRole("region", { name: "The demo board" })).toBeVisible();
    await expect(page.getByTestId("night-list").getByRole("region", { name: "The shop site" }).getByRole("listitem")).toHaveCount(2);
    await expect(page.getByTestId("night-list").getByRole("region", { name: "Jobs" }).getByRole("listitem")).toHaveCount(1);
    await expect(night(page)).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const dir = process.env.SB_SHOTS;
    if (dir !== undefined) await page.screenshot({ path: `${dir}/run-375.png` });
    await page.getByTestId("night-list").getByRole("region", { name: "The demo board" }).getByRole("button", { name: /Show the queue in order/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`axe finds no serious or critical issue on the run's graph (${scheme}); screenshot`, async ({ page }) => {
      // A whole-page axe scan ran past 30 s at load 42 (ticket 153's hub check); slow() gives it 90 s.
      test.slow();
      const { default: AxeBuilder } = await import("@axe-core/playwright");
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("/next/");
      await expect(night(page).locator(".react-flow__node-box")).toHaveCount(8);
      await page.waitForTimeout(800);
      const dir = process.env.SB_SHOTS;
      if (dir !== undefined) await page.screenshot({ path: `${dir}/run-${scheme}-1440.png` });
      const r = await new AxeBuilder({ page }).analyze();
      const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
    });
  }

  test("a ticket that starts and one that ends change in place, without a reload, keeping the zoom and the panel", async ({ page, request }) => {
    await page.goto("/next/");
    await expect(box(page, /Show the queue in order.*Queued\s*next 1/)).toBeVisible();
    await night(page).getByRole("button", { name: "Zoom in" }).click();
    await page.waitForTimeout(400);
    const view = (): Promise<string> => page.locator(".react-flow__viewport").first().evaluate((el) => (el as HTMLElement).style.transform);
    const where = (): Promise<string> => night(page).locator(".react-flow__node-box", { hasText: "Fix the sheet's focus" }).evaluate((el) => (el as HTMLElement).style.transform);
    const zoom = await view();
    const spot = await where();
    await page.evaluate(() => { (window as unknown as { kept: boolean }).kept = true; });
    await box(page, /Fix the sheet's focus/).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await request.post("/api/__advance");
    try {
      await expect(night(page).locator(".react-flow__node-box", { hasText: "Show the queue in order" })).toContainText("Running", { timeout: 8000 });
      await expect(night(page).locator(".react-flow__node-box", { hasText: "Run the board against the real hub" })).toContainText("Done");
      await expect(page.getByTestId("run-counts")).toHaveText("2 done · 3 running · 1 in checks · 2 fell short");
      expect(await view()).toBe(zoom);
      expect(await where()).toBe(spot);
      expect(await page.evaluate(() => (window as unknown as { kept?: boolean }).kept)).toBe(true);
      await expect(page.getByRole("dialog")).toBeVisible();
    } finally {
      await request.post("/api/__restore");
    }
  });
});

test.describe("Run tab", () => {
  const calls = async (page: Page): Promise<{ moveMap: number; map: number }> => (await page.request.get("/api/__calls")).json() as Promise<{ moveMap: number; map: number }>;
  const order = (page: Page) => page.getByTestId("map-block").evaluateAll((els) => els.map((e) => e.getAttribute("data-map")));

  test("?view=runs opens the Run tab on Flow, ?view=queue on its Queue tab", async ({ page }) => {
    for (const [v, tab] of [["runs", /^Flow/], ["queue", /^Queue/]] as const) {
      await page.goto(`/next/?view=${v}`);
      await expect(page.getByRole("tab", { name: /^Run\b/ })).toHaveAttribute("aria-selected", "true");
      await expect(page.getByRole("tablist", { name: "Run" }).getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
    }
    await expect(page.getByRole("tablist", { name: "Views" }).getByRole("tab", { name: /^Queue/ })).toHaveCount(0);
  });

  test("one line for the night, a block per map in the queue's order with its counts; Running now holds only what runs", async ({ page }) => {
    await page.goto("/next/?rt=maps");
    await expect(page.getByTestId("night-line")).toContainText("3 running · 1 next · 1 done · 2 fell short");
    expect(await order(page)).toEqual(["demo/board", "other/site"]);
    const board = page.getByRole("region", { name: "The demo board" });
    await expect(board.getByTestId("counts")).toHaveText("1 done · 2 running · 1 next · 1 fell short");
    // blocks with something running or fallen short start open, in run order: ended, running, next
    await expect(board.locator("li[data-mark]")).toHaveCount(5);
    await expect(board.locator("li[data-mark]").first()).toHaveAttribute("data-mark", "done");
    await expect(board.locator("li[data-mark]").last()).toHaveAttribute("data-mark", "next");
    await expect(board.locator("li[data-key='demo/board#3']")).toContainText("#1");
    await expect(page.getByRole("button", { name: /Unqueue this map: The demo board/ })).toBeVisible();
    // Running now: exactly the three workers; a ticket nobody queued is in neither it nor the blocks
    await expect(page.getByTestId("blocks")).not.toContainText("Drag a ticket into the queue");
    await runTab(page, "Now");
    await expect(page.getByRole("list", { name: "Running now" }).getByRole("listitem")).toHaveCount(3);
    await expect(page.getByRole("list", { name: "Running now" })).not.toContainText("Drag a ticket into the queue");
  });

  test("Running now also holds the tickets in their checks and second pass, and still no unqueued one", async ({ page, request }) => {
    await request.post("/api/__between");
    await page.goto("/next/?rt=now");
    const now = page.getByRole("list", { name: "Running now" });
    await expect(now.getByRole("listitem")).toHaveCount(5);
    await expect(now.locator("li[data-key='other/site#5']")).toContainText("in checks");
    await expect(now.locator("li[data-key='demo/board#4']")).toContainText("second pass");
    await expect(now).not.toContainText("Drag a ticket into the queue");
    await runTab(page, "Maps");
    await expect(page.getByTestId("blocks")).not.toContainText("Drag a ticket into the queue");
    await request.post("/api/__restore");
  });

  test("moving a map up calls the route and moves its block", async ({ page }) => {
    await page.goto("/next/?rt=maps");
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
    await page.goto("/next/?rt=maps");
    await expect(page.getByTestId("blocks")).toBeVisible();
    const wide = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    expect(wide).toBe(false);
  });

  test("screenshots of the Run tab", async ({ page }) => {
    const dir = process.env.SB_SHOTS;
    test.skip(dir === undefined, "SB_SHOTS names the folder to write to");
    const to = (n: string): string => `${dir ?? ""}/${n}`;
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/next/?rt=maps");
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
    await page.goto("/next/?rt=queue");
    const offer = page.getByRole("region", { name: "Queue a map" });
    const row = offer.locator("li[data-map='demo/batch']");
    await expect(row).toContainText("The batch map");
    await expect(row).toContainText("would add 5 tickets");
    await expect(page.getByRole("region", { name: "The batch map" })).toHaveCount(0);
    const before = await calls(page);
    await row.getByRole("button", { name: "Queue The batch map" }).click();
    await expect(page.getByRole("status")).toContainText("Queued 5 tickets of The batch map");
    await expect(offer.locator("li[data-map='demo/batch']")).toHaveCount(0);
    await runTab(page, "Maps");
    await expect(page.getByRole("region", { name: "The batch map" }).getByTestId("counts")).toHaveText("5 next");
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
  await expect(page).not.toHaveURL(/[?&]t=/);
  await found.getByRole("checkbox", { name: "Tick Draw the header" }).check();
  await page.getByTestId("selection-bar").getByRole("button", { name: /^Queue 1/ }).click();
  // queued, so no longer ticked: the bar is gone
  await expect(page.getByTestId("selection-bar")).toHaveCount(0);
  await runTab(page, "Maps");
  await expect(page.getByRole("region", { name: "The demo board" }).getByText("Draw the header")).toBeVisible();
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
  // a picture opens over the page, not in a new tab, and Esc returns to the list
  await done.getByRole("link", { name: "Open board-before.png and 1 more" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(page.context().pages()).toHaveLength(1);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await done.getByRole("button", { name: "Looks good" }).click();
  await expect(page.getByRole("region", { name: "Done" })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: /Waits for you/ })).toContainText("3");

  // Open the run: it is marked seen, so it leaves Waits for you and sits in History
  await page.getByRole("region", { name: "Failed" }).getByRole("button", { name: "Open the run" }).first().click();
  await expect(page).toHaveURL(/view=history/);
  await page.goBack(); // Back returns to Waits for you
  await expect(page).toHaveURL(/view=waits/);
  await expect(page.getByRole("region", { name: "Failed" }).getByRole("listitem")).toHaveCount(1);
  await expect(page.getByRole("tab", { name: /Waits for you/ })).toContainText("2");
});

test("Cmd-K opens the command menu with New job and Message", async ({ page }) => {
  await page.goto("/next/?rt=now");
  await expect(page.getByRole("list", { name: "Running now" })).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  const menu = page.getByRole("dialog");
  await expect(menu.getByRole("option", { name: "New job" })).toBeVisible();
  await menu.getByRole("option", { name: /Message/ }).click();
  await expect(page.getByRole("dialog").getByRole("heading", { name: "Message" })).toBeVisible();
});

test("the sidebar picks a map and every view narrows; the pick lives in the page link and the x clears it", async ({ page }) => {
  await page.goto("/next/?rt=now");
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

  // the search in the Queue tab finds only this map's open tickets; no block of the other map
  await runTab(page, "Queue");
  const found = page.getByTestId("ticket-rows");
  await expect(found.getByRole("row")).toHaveCount(3);
  await expect(found).toContainText("Draw the shop window");
  await expect(found).not.toContainText("Draw the header");
  await runTab(page, "Maps");
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
  // each key waits for the page to answer the one before: a loaded machine dropped the Enter on 2026-11-18
  await page.keyboard.press("1");
  await expect(page.getByRole("tab", { name: /^Run\b/ })).toHaveAttribute("aria-selected", "true");
  await runTab(page, "Now");
  await expect(page.getByRole("list", { name: "Running now" }).getByRole("listitem").first()).toBeVisible();
  await page.keyboard.press("j");
  await expect(page.locator("main li:focus")).toHaveCount(1);
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
  await expect(side.getByRole("button", { name: /^old/ })).toBeVisible();
  await sw.click();
  await expect(page).toHaveURL(/act=1/);
  await expect(sw).toHaveAttribute("aria-checked", "true");
  await expect(side.getByRole("button", { name: /^old/ })).toHaveCount(0);
  await expect(side.getByRole("button", { name: /^board / })).toBeVisible();
  await page.reload();
  await expect(side.getByRole("switch", { name: "Active only" })).toHaveAttribute("aria-checked", "true");
  await side.getByRole("switch", { name: "Active only" }).click();
  await expect(page).not.toHaveURL(/act=/);
  await expect(side.getByRole("button", { name: /^old/ })).toBeVisible();
});

test("every map shows in one list with no fold; a picked map stays picked after a reload", async ({ page }) => {
  await page.goto("/next/");
  const side = page.getByRole("navigation", { name: "Projects and maps" });
  await expect(side.getByRole("button", { name: /^site/ })).toBeVisible();
  await expect(side.getByRole("button", { name: /^old/ })).toBeVisible();
  await expect(side.getByRole("button", { name: /quiet map/ })).toHaveCount(0);
  await side.getByRole("button", { name: /^old/ }).click();
  await expect(page).toHaveURL(/map=other%2Fold/);
  await page.reload();
  await expect(side.getByRole("button", { name: /^old/ })).toHaveAttribute("aria-current", "page");
});

test("Cmd-K jumps to a map or a ticket", async ({ page }) => {
  await page.goto("/next/?rt=now");
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
  await page.goto("/next/?rt=now");
  await expect(page.getByRole("navigation", { name: "Projects and maps" })).toHaveCount(0);
  await page.getByRole("button", { name: "Projects and maps" }).click();
  const sheet = page.getByRole("dialog", { name: "Projects" });
  await sheet.getByRole("button", { name: /^other/ }).click();
  await expect(sheet).toHaveCount(0);
  await expect(page).toHaveURL(/project=other/);
  await expect(page.getByRole("list", { name: "Running now" }).getByRole("listitem")).toHaveCount(1);
});

test.describe("The live run and its history", () => {
  test.beforeEach(async ({ request }) => {
    await request.post("/api/__restore");
  });
  test.afterEach(async ({ request }) => {
    await request.post("/api/__restore");
  });
  const head = (page: Page) => page.getByTestId("run-head");
  const noSideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

  test("the head shows the live run's name, start, who started it and one line of counts; nothing of an ended run is on the tab", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/next/");
    await expect(head(page)).toHaveAttribute("data-live", "true");
    await expect(head(page).getByTestId("run-name")).toHaveText("Night of 2026-11-14, 22:45");
    await expect(head(page).getByTestId("run-started")).toContainText("by Charting the board");
    await expect(head(page).getByTestId("head-counts")).toHaveText("1 done · 3 running · 1 next · 2 fell short");
    // the ended run's tickets are nowhere: not in the graph, not in the blocks, not in the line
    const graph = page.getByTestId("night-graph");
    await expect(graph.locator(".react-flow__node-box")).toHaveCount(7);
    await expect(graph.getByText("Sweep the old attic")).toHaveCount(0);
    await expect(graph.getByText("The old attic")).toHaveCount(0);
    await runTab(page, "Maps");
    await expect(page.getByTestId("blocks")).toBeVisible();
    await expect(page.getByTestId("blocks").getByText("The old attic")).toHaveCount(0);
    await expect(page.getByTestId("blocks").getByText("Drag a ticket into the queue")).toHaveCount(0);
    await runTab(page, "Now");
    await expect(page.getByRole("list", { name: "Running now" }).getByRole("listitem")).toHaveCount(3);
    expect(errors).toEqual([]);
  });

  test("a project shows frames for its maps, never a bare list; a map shows its own graph", async ({ page }) => {
    await page.goto("/next/?project=demo");
    const g = page.getByTestId("night-graph");
    await expect(g.getByText("The demo board", { exact: true })).toBeVisible();
    await expect(g.getByText("The shop site", { exact: true })).toHaveCount(0);
    await page.goto("/next/?project=other");
    await expect(page.getByTestId("night-graph").getByText("The shop site", { exact: true })).toBeVisible();
    await expect(page.getByTestId("night-graph").getByText("The old attic", { exact: true })).toHaveCount(0);
    await page.goto("/next/?project=demo&map=demo%2Fboard");
    await expect(page.getByTestId("map-graph")).toBeVisible();
    await expect(page.getByTestId("night-graph")).toHaveCount(0);
  });

  test("the name is renamed by a click", async ({ page }) => {
    await page.goto("/next/");
    await head(page).getByRole("button", { name: /^Rename the run/ }).click();
    await page.getByRole("textbox", { name: "Run name" }).fill("The big night");
    await page.keyboard.press("Enter");
    await expect(head(page).getByTestId("run-name")).toHaveText("The big night");
  });

  test("Stop run asks once, posts mode after, and the head reads stopping and names what still runs", async ({ page, request }) => {
    await page.goto("/next/");
    await head(page).getByRole("button", { name: "Stop run" }).click();
    const ask = head(page).getByRole("group", { name: "Stop the run?" });
    await expect(ask).toContainText("Let the 3 running tickets finish, then end the run. 1 ticket will not be reached.");
    await ask.getByRole("button", { name: "Keep it running" }).click();
    await expect(ask).toHaveCount(0);
    expect(await (await request.get("/api/__night-stops")).json()).toEqual([]);
    await head(page).getByRole("button", { name: "Stop run" }).click();
    await head(page).getByRole("button", { name: "Stop after what runs" }).click();
    await expect(head(page)).toHaveAttribute("data-stopping", "true");
    await expect(head(page).getByTestId("stopping")).toContainText("Stopping: waiting for");
    await expect(head(page).getByTestId("stopping")).toContainText("Run the board against the real hub");
    await expect(head(page).getByRole("button", { name: "Stop run" })).toHaveCount(0);
    expect(await (await request.get("/api/__night-stops")).json()).toEqual(["after"]);
  });

  test("with no run live the tab says so, shows the last run as one line, queuing a map waits for Start, and Start opens the run", async ({ page, request }) => {
    await request.post("/api/__nolive");
    await page.goto("/next/");
    await expect(head(page)).toHaveAttribute("data-live", "false");
    await expect(head(page)).toContainText("No run is live");
    await expect(page.getByTestId("last-run")).toContainText("Night of 2026-11-14, 22:45");
    await expect(page.getByTestId("last-run")).toContainText("Finished");
    await runTab(page, "Maps");
    await expect(page.getByTestId("blocks")).toHaveCount(0);
    await runTab(page, "Queue");
    const offer = page.getByRole("region", { name: "Queue a map" });
    await offer.locator("li[data-map='demo/batch']").getByRole("button", { name: "Queue The batch map" }).click();
    // queueing never starts a run: the work waits for Start
    await expect(head(page)).toHaveAttribute("data-live", "false");
    await expect(page.getByTestId("waits-start")).toHaveText("5 queued, waiting for Start. Nothing runs until you press it.");
    await head(page).getByTestId("run-start").click();
    await expect(head(page)).toHaveAttribute("data-live", "true");
    await expect(head(page).getByTestId("head-counts")).toHaveText("5 next");
  });

  test("History lists two runs newest first; the ended one opens to its graph, a not reached ticket, links and filters", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/next/");
    await page.keyboard.press("3");
    const runs = page.getByRole("list", { name: "Runs" });
    await expect(runs.getByRole("listitem")).toHaveCount(2);
    await expect(runs.getByRole("listitem").first()).toContainText("Night of 2026-11-14, 22:45");
    await expect(runs.getByRole("listitem").first()).toContainText("Live");
    await expect(runs.getByRole("listitem").nth(1)).toContainText("Stopped by you");
    await expect(runs.getByRole("listitem").nth(1)).toContainText("1 done · 1 fell short · 2 not reached");
    await runs.getByRole("button", { name: "Night of 2026-11-13, 21:30" }).click();
    await expect(page).toHaveURL(/night=n-old/);
    await expect(page.getByTestId("night-detail")).toContainText("Stopped by you");
    await expect(page.getByTestId("night-graph").locator(".react-flow__node-box")).toHaveCount(2);
    const lost = page.getByTestId("not-reached");
    await expect(lost.locator("li[data-mark='not reached']")).toHaveCount(2);
    await expect(lost).toContainText("Batch A");
    const tickets = page.getByRole("list", { name: "Tickets of the run" });
    await expect(tickets.getByRole("listitem")).toHaveCount(2);
    await expect(tickets.locator("li[data-key='demo/board#2']").getByRole("link", { name: "Report" })).toHaveAttribute("href", /^obsidian:/);
    await expect(tickets.locator("li[data-key='demo/board#2']").getByRole("link", { name: "Log" })).toHaveAttribute("href", /^obsidian:/);
    // the filters work inside the run
    await page.getByRole("group", { name: "Outcome" }).getByRole("button", { name: "failed" }).click();
    await expect(tickets.getByRole("listitem")).toHaveCount(1);
    await expect(tickets).toContainText("Sweep the old attic");
    await page.getByRole("group", { name: "Outcome" }).getByRole("button", { name: "failed" }).click();
    await page.getByRole("searchbox", { name: "Search tickets" }).fill("drag");
    await expect(tickets.getByRole("listitem")).toHaveCount(1);
    await page.getByRole("searchbox", { name: "Search tickets" }).fill("");
    // a reload on the link opens the same run
    await page.reload();
    await expect(page.getByTestId("night-detail")).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("Queue these again queues the two not reached tickets, and Start opens a run with them", async ({ page, request }) => {
    await request.post("/api/__nolive");
    await page.goto("/next/?view=history&night=n-old");
    await page.getByTestId("not-reached").getByRole("button", { name: "Queue these again" }).click();
    await expect(page.getByRole("tab", { name: /^Run\b/ })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("waits-start")).toContainText("2 queued, waiting for Start");
    await head(page).getByTestId("run-start").click();
    await expect(head(page)).toHaveAttribute("data-live", "true");
    await expect(head(page).getByTestId("head-counts")).toHaveText("2 next");
  });

  test("at 375 px the head, the history and an opened run are one column and nothing scrolls sideways", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    for (const url of ["/next/", "/next/?view=history", "/next/?view=history&night=n-old", "/next/?project=demo"]) {
      await page.goto(url);
      await page.waitForTimeout(300);
      expect(await noSideways(page), url).toBe(true);
    }
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`axe finds no serious or critical issue on the head and an opened run (${scheme})`, async ({ page }) => {
      // A whole-page axe scan ran past 30 s at load 42 (ticket 153's hub check); slow() gives it 90 s.
      test.slow();
      const { default: AxeBuilder } = await import("@axe-core/playwright");
      await page.emulateMedia({ colorScheme: scheme });
      for (const url of ["/next/", "/next/?view=history&night=n-old"]) {
        await page.goto(url);
        await page.waitForTimeout(700);
        const r = await new AxeBuilder({ page }).analyze();
        const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
        expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`), url).toEqual([]);
      }
    });
  }

  /** Screenshots for the report: SB_SHOTS=<folder> writes them; without it this test does nothing. */
  test("screenshots of the head and of History", async ({ page }) => {
    const dir = process.env.SB_SHOTS;
    test.skip(dir === undefined, "SB_SHOTS names the folder to write to");
    const to = (n: string): string => `${dir ?? ""}/${n}`;
    await page.goto("/next/");
    await expect(head(page)).toHaveAttribute("data-live", "true");
    await page.waitForTimeout(900);
    await page.screenshot({ path: to("run-head-1440.png") });
    await page.goto("/next/?view=history&night=n-old");
    await expect(page.getByTestId("night-detail")).toBeVisible();
    await page.waitForTimeout(900);
    await page.screenshot({ path: to("history-run-1440.png"), fullPage: true });
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/next/");
    await expect(head(page).getByTestId("run-started")).toBeVisible();
    await page.screenshot({ path: to("run-head-375.png") });
    await page.goto("/next/?view=history");
    await expect(page.getByRole("list", { name: "Runs" })).toBeVisible();
    await page.screenshot({ path: to("history-375.png") });
    await page.goto("/next/?view=history&night=n-old");
    await expect(page.getByTestId("night-detail")).toBeVisible();
    await page.waitForTimeout(500);
    await page.screenshot({ path: to("history-run-375.png"), fullPage: true });
  });
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
    // A whole-page axe scan ran past 30 s at load 42 (ticket 153's hub check); slow() gives it 90 s.
    test.slow();
    const { default: AxeBuilder } = await import("@axe-core/playwright");
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto(`/next/?view=${view}`);
    await expect(page.getByRole("tablist", { name: "Views" }).getByRole("tab", { selected: true })).toBeVisible();
    await page.waitForTimeout(500);
    const r = await new AxeBuilder({ page }).analyze();
    const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
  });
}

test.describe("Run tab: who is on each ticket", () => {
  test("the head names the session in charge, a row with a worker opens its panel, Helpers and joined chats only", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/next/?rt=maps");
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
    await runTab(page, "Now");
    const other = page.getByTestId("other-chats");
    await expect(other).toContainText("1 live");
    await expect(other).toContainText("Reading the old notes");
    await expect(other).toContainText("implementer");
    await expect(page.getByText("A chat that never joined")).toHaveCount(0);
    await expect(other).toContainText("Helpers (1)");
    // the tab counts running workers
    await expect(page.getByRole("tab", { name: /^Run/ })).toContainText("3");
    expect(errors).toEqual([]);
  });

  test("a silent worker's row carries the silent mark", async ({ page }) => {
    await page.goto("/next/?rt=maps");
    const row = page.locator("li[data-key='demo/board#8']");
    await expect(row).toHaveAttribute("data-worker", "silent");
    await expect(row.getByTestId("silent")).toBeVisible();
    await expect(page.locator("li[data-key='demo/board#5']").getByTestId("silent")).toHaveCount(0);
  });

  test("?view=sessions and a sess link land on the Run tab with the panel open", async ({ page }) => {
    await page.goto("/next/?view=sessions");
    await expect(page.getByRole("tablist", { name: "Views" }).getByRole("tab", { selected: true })).toContainText("Run");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.goto("/next/?view=sessions&sess=demo%2Fboard%235");
    // the panel is modal: the tabs behind it are hidden from the accessibility tree until it closes
    await expect(page.getByRole("dialog").getByRole("list", { name: "Last actions" })).toBeVisible();
    await expect(page.getByRole("tablist", { name: "Views", includeHidden: true }).getByRole("tab", { selected: true, includeHidden: true })).toContainText("Run");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("tablist", { name: "Views" }).getByRole("tab", { selected: true })).toContainText("Run");
  });

  test("at 375 px nothing scrolls sideways", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/next/?rt=now");
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
    const body = (await res.json()) as { queue: { night: string; items: Record<string, unknown>[] } };
    const t = Date.now() / 1000;
    const failed = body.queue.items.find((i) => i.key === "demo/board#6");
    body.queue.items.push({
      links: failed?.links, night: body.queue.night,
      key: "demo/board#2", kind: "ticket", agent: null, state: "recheck", tries: 1, started: t - 1800, ended: t - 600,
      commit: "fedcba9876543210", rechecks: 1, recheck_at: t + 600, run: "/vault/runs/2026-11-13-board", log: "/vault/runs/2026-11-13-board/2.log",
      note: "check could not run: pnpm test exited 75 (the tool it needs did not answer); rechecking in 10 minutes (1 of 6)",
      checks: [{ cmd: "pnpm test", code: 75, secs: 300, tail: "Unity Editor did not answer" }],
    });
    await route.fulfill({ response: res, json: body });
  });
  await page.goto("/next/?rt=maps");
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
    // the map runs left to right: A, B and C (none comes after another) share the first step, one under the other
    const first = async () => {
      const r = [await rect("Batch A"), await rect("Batch B"), await rect("Batch C")];
      const area = await graph.boundingBox();
      if (area === null) throw new Error("the graph is not on screen");
      return { left: Math.min(...r.map((b) => b.x)), top: Math.min(...r.map((b) => b.y)), last: r.reduce((m, b) => (b.y > m.y ? b : m)), area };
    };
    // from the empty space left of the first step to the middle of its lowest box: A, B and C only
    const tickFirst = async () => {
      const f = await first();
      await page.mouse.move(f.left - 6, f.top - 6);
      await page.mouse.down();
      await page.mouse.move(f.last.x + f.last.width / 2, f.last.y + f.last.height / 2, { steps: 8 });
      await page.mouse.up();
    };
    const [a, d] = [await rect("Batch A"), await rect("Batch D")];
    await tickFirst();
    const bar = page.getByTestId("selection-bar");
    await expect(bar).toBeVisible();
    await expect(bar).toContainText("3");
    await expect(graph.getByText("Ticked")).toHaveCount(3);
    expect(d.x).toBeGreaterThan(a.x + a.width);
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
      await tickFirst();
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
    await expect(bar).toHaveCount(0);
    await expect(graph.getByText("Ticked")).toHaveCount(0);
    // queue three by a box again. The page may have scrolled meanwhile so far that the graph's top edge sits
    // under the sticky header, where a drag would start on the header: bring the graph to the middle, then measure again
    await graph.evaluate((el) => { el.scrollIntoView({ block: "center" }); });
    await tickFirst();
    await expect(graph.getByText("Ticked")).toHaveCount(3);
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
      // A whole-page axe scan ran past 30 s at load 42 (ticket 153's hub check); slow() gives it 90 s.
      test.slow();
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
      // A whole-page axe scan ran past 30 s at load 42 (ticket 153's hub check); slow() gives it 90 s.
      test.slow();
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

test.describe("Run tab: why it waits, how many at once, which account and model", () => {
  interface Calls { parallel: { repo: string; n: number }[]; agents: string[][]; itemAgent: Record<string, unknown>[] }
  const calls = async (page: Page): Promise<Calls> => (await page.request.get("/api/__calls")).json() as Promise<Calls>;
  const noSideways = (page: Page): Promise<boolean> => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

  test("a waiting row says what it waits for; plus calls the parallel route and the line changes", async ({ page }) => {
    await page.goto("/next/?rt=maps");
    const row = page.locator("li[data-key='demo/board#3']");
    await expect(row.getByTestId("wait-reason")).toHaveText("waits for Run the board against the real hub: both change src/");
    await page.getByRole("button", { name: /^At once and accounts/ }).click();
    const line = page.getByTestId("repo-line").first();
    await expect(line.getByTestId("repo-words")).toHaveText("2 running of 2 at once · 0 more could run side by side");
    await line.getByRole("button", { name: /one more at once/ }).click();
    await expect(line.getByTestId("repo-words")).toHaveText("2 running of 3 at once · 1 more could run side by side");
    expect((await calls(page)).parallel).toEqual([{ repo: "/demo", n: 3 }]);
    await line.getByRole("button", { name: /one fewer at once/ }).click();
    await expect(line.getByTestId("repo-words")).toContainText("of 2 at once");
  });

  test("an account's two bars, and its switch calls the agents route", async ({ page }) => {
    await page.goto("/next/");
    await page.getByRole("button", { name: /^At once and accounts/ }).click();
    const spare = page.locator("[data-testid=account-line][data-account='spare']");
    await expect(spare.getByRole("progressbar", { name: "5 hours use" })).toHaveAttribute("aria-valuenow", "90");
    await expect(spare.getByRole("progressbar", { name: "week use" })).toHaveAttribute("aria-valuenow", "70");
    await expect(spare.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    await spare.getByRole("switch").click();
    await expect(spare.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect((await calls(page)).agents.at(-1)).toEqual(["main", "spare"]);
    await spare.getByRole("switch").click();
    await expect(spare.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    // the last account cannot be switched off
    await expect(page.locator("[data-testid=account-line][data-account='main']").getByRole("switch")).toBeDisabled();
  });

  test("a row's menu sets its account and model; the row shows them; ticked rows get the same from the bar", async ({ page }) => {
    await page.goto("/next/?rt=maps");
    const row = page.locator("li[data-key='demo/board#3']");
    await row.getByRole("button", { name: /the account and model for/ }).click();
    await page.getByRole("option", { name: /^spare/ }).click();
    await expect(row.getByTestId("row-agent")).toHaveText("spare");
    await row.getByRole("button", { name: /the account and model for/ }).click();
    await page.getByRole("listbox", { name: "Model" }).getByRole("option", { name: "opus" }).click();
    await expect(row.getByTestId("row-agent")).toHaveText("spare · opus");
    const c = (await calls(page)).itemAgent;
    expect(c.slice(-2)).toEqual([{ key: "demo/board#3", name: "spare" }, { key: "demo/board#3", model: "opus" }]);
    await row.getByRole("checkbox").check();
    const bar = page.getByTestId("tick-bar");
    await expect(bar).toContainText("1 ticket ticked");
    await bar.getByRole("button", { name: "Set account and model" }).click();
    await page.getByRole("option", { name: /^Tonight's accounts/ }).click();
    await expect(row.getByTestId("row-agent")).toHaveText("pool · opus");
    await expect(bar).toHaveCount(0);
  });

  test("at 375 px nothing scrolls sideways, with a row ticked", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/next/?rt=maps");
    await page.locator("li[data-key='demo/board#3']").getByRole("checkbox").check();
    await expect(page.getByTestId("tick-bar")).toBeVisible();
    expect(await noSideways(page)).toBe(true);
  });

  for (const [scheme, w] of [["light", 1440], ["dark", 375]] as const) {
    test(`axe is clean and a picture is taken (${scheme}, ${String(w)} px)`, async ({ page }) => {
      // A whole-page axe scan ran past 30 s at load 42 (ticket 153's hub check); slow() gives it 90 s.
      test.slow();
      const { default: AxeBuilder } = await import("@axe-core/playwright");
      await page.setViewportSize({ width: w, height: w === 375 ? 800 : 900 });
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("/next/?rt=maps");
      await page.locator("li[data-key='demo/board#3']").getByRole("checkbox").check();
      await page.waitForTimeout(500);
      const dir = process.env.SB_SHOTS;
      if (dir !== undefined) await page.screenshot({ path: `${dir}/limits-${String(w)}-${scheme}.png`, fullPage: true });
      const r = await new AxeBuilder({ page }).analyze();
      const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
    });
  }
});

test("Review finished now: off while no ticket waits for a review, on with the count and the next look once one has landed", async ({ page, request }) => {
  await request.post("/api/__restore");
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/next/?rt=maps");
  const none = page.getByRole("button", { name: "Review finished now" });
  await expect(none).toBeDisabled();
  await request.post("/api/__between");
  const one = page.getByRole("button", { name: "Review 1 finished now" });
  await expect(one).toBeEnabled({ timeout: 10_000 });
  await expect(page.getByTestId("review-now")).toContainText("The next timed look is at");
  const dir = process.env.SB_SHOTS;
  if (dir !== undefined) await page.screenshot({ path: `${dir}/126-phone.png` });
  await request.post("/api/__restore");
});
