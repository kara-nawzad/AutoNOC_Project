import { expect, test } from "@playwright/test";

// Run against an isolated local simulator, never a shared production instance.
test("live controls, map inspector, scenarios, and mobile layout", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (msg) => {
    if (
      msg.type() === "error" &&
      !msg.text().includes("Failed to load resource")
    )
      errors.push(msg.text());
  });
  await request.post("/api/control/pause");
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Network overview" }),
  ).toBeVisible();
  await expect(page.locator(".kpi-card")).toHaveCount(6);
  const before = (await (await request.get("/api/health")).json()).tick;
  await page
    .getByRole("button", { name: "Advance one simulation tick" })
    .click();
  await expect
    .poll(async () => (await (await request.get("/api/health")).json()).tick)
    .toBe(before + 1);
  await page.waitForTimeout(1300);
  expect((await (await request.get("/api/health")).json()).tick).toBe(
    before + 1,
  );

  await page.getByRole("button", { name: "Find a site..." }).click();
  const snapshot = await (await request.get("/api/data")).json();
  const node = snapshot.nodes.find((n: { status: number }) => n.status === 0);
  await page
    .getByRole("textbox", { name: "Search site ID or district" })
    .fill(node.id);
  await page.locator(".search-results button").first().click();
  await expect(
    page.getByRole("complementary", { name: `Inspector for ${node.id}` }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Inject fault on this site" }).click();
  await page.locator("dialog select").nth(1).selectOption("3");
  await page
    .locator("dialog")
    .getByRole("button", { name: "Inject fault", exact: true })
    .click();
  await expect(page.locator(".inspector .site-status")).toHaveText(
    "VSWR Alarm",
  );
  await page.getByRole("button", { name: "Close site inspector" }).click();

  await page.getByRole("button", { name: "Cut fiber", exact: true }).click();
  await page.getByRole("button", { name: "Confirm double cut" }).click();
  await expect(
    page
      .locator(".incident-title")
      .filter({ hasText: "Fiber ring isolated" })
      .first(),
  ).toBeVisible();
  await expect(page.locator(".cut-pulse").first()).toBeAttached();
  await page.getByRole("button", { name: "Map layers" }).click();
  await page.getByLabel("fiber", { exact: true }).uncheck();
  await expect(page.locator(".fiber-flow")).toHaveCount(0);
  await page.getByLabel("fiber", { exact: true }).check();
  await page.getByRole("button", { name: "Map layers" }).click();

  await page
    .getByRole("button", { name: "Maintenance fleet", exact: true })
    .click();
  await expect(page.locator(".fleet-card")).toHaveCount(snapshot.teams.length);
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Open network event history" })
    .click();
  await expect(page.locator(".history-row").first()).toBeVisible();
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Network overview" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
  await page.setViewportSize({ width: 1512, height: 982 });
  await page.screenshot({ path: "test-results/desktop.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("approval failure rolls back optimistic removal; veto removes the intent", async ({
  page,
  request,
}) => {
  const baseline = await (await request.get("/api/data")).json();
  const cfg = await (await request.get("/api/config")).json();
  const node = baseline.nodes[0];
  let pending = [
    {
      action_id: 99991,
      node_id: node.id,
      node: node.id,
      cls: 3,
      probability: 0.8,
      action: "pre_dispatch",
      tier: 2,
      label: cfg.status_names["3"],
      created_tick: baseline.tick,
      state: "pending",
    },
  ];
  // Test-only network fixtures exercise both success and rejection paths.
  await page.route("**/api/delta?*", (route) =>
    route.fulfill({ json: { ...baseline, ai: { ...baseline.ai, pending } } }),
  );
  await page.route("**/api/control/approve/99991?*", (route) =>
    route.fulfill({ status: 409, json: { detail: "Test fleet unavailable" } }),
  );
  await page.route("**/api/control/veto/99991?*", async (route) => {
    pending = [];
    await route.fulfill({ json: { ok: true } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Approve pre-dispatch" }).click();
  await expect(page.getByRole("alert")).toContainText("Test fleet unavailable");
  await expect(
    page.getByRole("button", { name: "Approve pre-dispatch" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Veto action 99991" }).click();
  await expect(
    page.getByRole("button", { name: "Veto action 99991" }),
  ).toHaveCount(0);
});

test("reconnect retains last telemetry and reduced motion stops decoration", async ({
  page,
  request,
}) => {
  await request.post("/api/control/pause");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.locator(".kpi-card")).toHaveCount(6);
  const clock = await page.locator(".sim-clock").textContent();
  await page.route("**/api/delta?*", (route) => route.abort());
  await expect(page.getByRole("alert")).toContainText(
    "Telemetry connection interrupted",
  );
  expect(await page.locator(".sim-clock").textContent()).toBe(clock);
  expect(
    await page
      .locator(".fiber-flow")
      .first()
      .evaluate((el) => getComputedStyle(el).animationName),
  ).toBe("none");
  await page.unroute("**/api/delta?*");
  await page.getByRole("button", { name: "Reconnect", exact: true }).click();
  await expect(page.locator(".connection-banner")).toHaveCount(0);
});
