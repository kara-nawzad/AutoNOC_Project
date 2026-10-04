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
  const { run_id: initialRunId } = await (
    await request.get("/api/health")
  ).json();
  await request.post("/api/control/pause", {
    params: { run_id: initialRunId },
  });
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

test("run reset shows Day 1, clears stale UI state, and histories completions by time", async ({
  page,
  request,
}) => {
  const baseline = await (await request.get("/api/data")).json();
  const healthy = baseline.nodes.find(
    (node: { status: number }) => node.status === 0,
  );
  if (!healthy) throw new Error("test world has no healthy site to select");
  let frame = {
    ...baseline,
    run_id: "browser-run-before-reset",
    reset_notice: false,
    run_error: null,
    tick: 0,
    kpis: { ...baseline.kpis, tick: 0, sim_time: "D1 00:00" },
    dashboard: {
      ...baseline.dashboard,
      current: { ...baseline.dashboard.current, tick: 0, sim_time: "D1 00:00" },
      history: [
        { ...baseline.dashboard.current, tick: 0, sim_time: "D1 00:00" },
      ],
    },
    logs: [],
    control: { ...baseline.control, paused: true },
  };
  const completedAt = "2026-10-04T08:15:00Z";
  await page.route("**/api/delta?*", (route) => route.fulfill({ json: frame }));
  await page.route("**/api/history", (route) =>
    route.fulfill({
      json: {
        summaries: [
          {
            completed_at: completedAt,
            simulated_days: 30,
            completed_sim_time: "D30 23:55",
            seed: 42,
            availability: 98.25,
            injected: 23,
            masked: 4,
            repairs: 21,
            mttr_min: 45.5,
            ats_failures: 1,
            fuel_thefts: 2,
            active_incidents: 3,
            ai_enabled: true,
            ai_mode: "ml",
            pre_empted: 6,
            acted_upon: 8,
            false_dispatches: 1,
            crew_hours_saved: 5.2,
            precision: 0.86,
          },
        ],
      },
    }),
  );
  await page.goto("/");
  await expect(page.locator(".sim-clock")).toContainText("D1 00:00");
  await expect(page.locator(".sim-clock")).not.toContainText("SEED");

  await page.getByRole("button", { name: "Find a site..." }).click();
  await page
    .getByRole("textbox", { name: "Search site ID or district" })
    .fill(healthy.id);
  await page.locator(".search-results button").first().click();
  await expect(
    page.getByRole("complementary", { name: `Inspector for ${healthy.id}` }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Inject fault on this site" }).click();
  await expect(page.locator("dialog")).toBeVisible();

  frame = {
    ...frame,
    run_id: "browser-run-after-reset",
    reset_notice: true,
    tick: 0,
    kpis: { ...frame.kpis, tick: 0, sim_time: "D1 00:00" },
    dashboard: {
      ...frame.dashboard,
      current: { ...frame.dashboard.current, tick: 0, sim_time: "D1 00:00" },
      history: [{ ...frame.dashboard.current, tick: 0, sim_time: "D1 00:00" }],
    },
    logs: [],
  };
  await expect(page.getByRole("status")).toContainText(
    "Demo restarted · Day 1",
  );
  await expect(page.locator("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("complementary", { name: `Inspector for ${healthy.id}` }),
  ).toHaveCount(0);
  await expect(page.locator(".sim-clock")).toContainText("D1 00:00");

  await page
    .getByRole("button", { name: "Open network event history" })
    .click();
  await page.getByRole("tab", { name: "Completed demos" }).click();
  const completion = page.locator(".run-summary-card time");
  await expect(completion).toHaveAttribute("datetime", completedAt);
  await expect(page.getByText("30 simulated days")).toBeVisible();
  expect(await page.locator("body").innerText()).not.toMatch(/Cycle\s+\d+/i);
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
  const { run_id: currentRunId } = await (
    await request.get("/api/health")
  ).json();
  await request.post("/api/control/pause", {
    params: { run_id: currentRunId },
  });
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

test("executive impact is transparent and long traffic windows use server samples", async ({
  page,
  request,
}) => {
  const { run_id: runId } = await (await request.get("/api/health")).json();
  await request.post("/api/control/pause", { params: { run_id: runId } });
  await request.post("/api/control/ai", {
    params: { run_id: runId, enabled: false },
  });

  await page.goto("/");
  const roiPill = page.locator(".roi-pill.inactive");
  await expect(roiPill).toBeVisible();
  await roiPill.click();
  const impact = page.getByRole("dialog", {
    name: /A1 Autonomous Intent — Economic & Operational Impact/,
  });
  await expect(impact).toBeVisible();
  await expect(impact).toContainText("19,418 units lower");
  await expect(impact).toContainText("8.6 h used · not saved");
  await expect(impact).toContainText("it is not USD");
  await page.keyboard.press("Escape");
  await expect(impact).toHaveCount(0);

  await page.getByRole("button", { name: "24h", exact: true }).click();
  await expect(page.locator(".traffic-card .chart-axis")).toContainText(
    "SIM MIN",
  );
  await expect(page.locator(".chart-provenance")).toContainText(
    "Actual current-run samples",
  );
  await page.getByRole("button", { name: "7d", exact: true }).click();
  await expect(page.locator(".traffic-card .chart-axis")).toContainText(
    "SAMPLES",
  );
  const history = await (
    await request.get(`/api/telemetry/history?timeframe=7d&run_id=${runId}`)
  ).json();
  expect(history.run_id).toBe(runId);
  expect(history.samples.length).toBeGreaterThan(0);
  const health = await (await request.get("/api/health")).json();
  expect(history.samples.at(-1).tick).toBe(health.tick);
});
