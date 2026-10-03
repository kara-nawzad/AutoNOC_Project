import { expect, test } from "@playwright/test";

test("trucks keep moving between polls with fractional pixels, then stop on pause", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 900, height: 650 });
  // Deterministic test-only readouts; do not inject faults or pause the shared
  // running simulator. Small movement exposes Leaflet's old integer-pixel hops.
  const baseline = await (await request.get("/api/data")).json();
  const config = await (await request.get("/api/config")).json();
  let tick = 0;
  let paused = false;
  const id = baseline.teams[0].id;
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.route("https://tiles.openfreemap.org/**", (route) =>
    route.abort(),
  );
  await page.route("**/api/delta?*", (route) => {
    if (!paused) tick++;
    return route.fulfill({
      json: {
        ...baseline,
        tick,
        run_id: "crew-render-regression",
        control: { ...baseline.control, paused },
        teams: [
          {
            ...baseline.teams[0],
            lat: config.map_center[0],
            lon: config.map_center[1] + tick * 0.0015,
            state: "EN_ROUTE",
            available: false,
          },
        ],
      },
    });
  });
  await page.goto("/");
  const truck = page.locator(`[data-crew-id="${id}"]`);
  await expect(truck).toBeVisible();
  // Leave the basemap out of this movement measurement, not the actual map
  // projection/marker DOM. Its independently tested WebGL layer costs CPU.
  await page.getByRole("button", { name: "Map layers" }).click();
  await page.getByLabel("streets", { exact: true }).uncheck();
  await page.getByRole("button", { name: "Map layers" }).click();
  await page.locator(".map-stage").scrollIntoViewIfNeeded();
  await page.waitForTimeout(2300);
  const samples = await truck.evaluate(
    (element) =>
      new Promise<{ x: number; t: number }[]>((resolve) => {
        const points: { x: number; t: number }[] = [];
        const start = performance.now();
        const draw = (t: number) => {
          points.push({
            x: new DOMMatrixReadOnly(getComputedStyle(element).transform).m41,
            t,
          });
          if (t - start >= 2200) resolve(points);
          else requestAnimationFrame(draw);
        };
        requestAnimationFrame(draw);
      }),
  );
  // Software-rendered CI browsers can deliver far fewer than 60 FPS; verify
  // continuity on the frames actually painted, not the host's GPU throughput.
  expect(samples.length).toBeGreaterThan(5);
  const deltas = samples.slice(1).map((s, i) => s.x - samples[i].x);
  const moving = deltas.filter((dx) => dx > 0.0001).length;
  expect(moving / deltas.length).toBeGreaterThan(0.9);
  expect(deltas.every((dx) => dx >= 0)).toBe(true);
  expect(samples.some((s) => Math.abs(s.x - Math.round(s.x)) > 0.01)).toBe(
    true,
  );
  // Normalize by actual frame duration: a missed GPU frame legitimately covers
  // more pixels. The old rush-and-stop easing caused a much larger speed swing.
  const speeds = deltas.map((dx, i) => dx / (samples[i + 1].t - samples[i].t));
  expect(Math.max(...speeds) / Math.min(...speeds)).toBeLessThan(3);
  console.log(
    `Crew render: ${samples.length} sampled frames; ${Math.round((100 * moving) / deltas.length)}% moving; largest step ${Math.max(...deltas).toFixed(3)}px`,
  );

  paused = true;
  await expect(
    page.getByRole("button", { name: "Resume simulation" }),
  ).toBeVisible();
  await page.waitForTimeout(350);
  const stopped = await truck.getAttribute("style");
  await page.waitForTimeout(650);
  expect(await truck.getAttribute("style")).toBe(stopped);
});
