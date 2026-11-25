import { expect, test } from "@playwright/test";

test("a running ticket's panel shows its worker live, and a steer is sent and shown as read", async ({ page }) => {
  await page.request.post("/api/__restore");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/next/?t=demo%2Fboard%235");
  const sheet = page.getByRole("dialog");
  const live = sheet.getByRole("region", { name: "Live" });
  // the worker's last sentence heads it; its sentences, calls and a failed result are in the feed
  await expect(live).toContainText("Now: Fixing the cleared-job row, then running the tests again.");
  const feed = live.getByRole("log", { name: "Live feed" });
  await expect(feed).toContainText("Reading the ticket and the board's tests first.");
  await expect(feed.getByRole("img", { name: "failed" })).toHaveCount(1);
  // a call opens on its result
  await feed.getByText("pnpm vitest run src/board.test.ts").click();
  await expect(feed).toContainText("1 failed: the board draws no row for a cleared job");
  // the log grows: the next read adds the next call, still running
  await expect(feed.getByRole("img", { name: "running" })).toHaveCount(1);
  // one tap sends a steer; the worker reads it at its next step and answers in the feed
  await live.getByRole("button", { name: "Wrap up now" }).click();
  await expect(live.getByRole("list", { name: "Your messages to it" })).toContainText(/read at \d\d:\d\d/);
  await expect(feed).toContainText("Got it: wrapping up after this test run.");
  // a typed message goes too
  await live.getByLabel("Message to the worker").fill("Leave the CSS alone.");
  await live.getByRole("button", { name: "Send" }).click();
  await expect(live.getByLabel("Message to the worker")).toHaveValue("");
  await expect(feed).toContainText("Leave the CSS alone.");
  expect(errors).toEqual([]);
});
