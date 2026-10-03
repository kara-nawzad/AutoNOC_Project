import { expect, test, type Page } from "@playwright/test";
import { GeoJSONVT } from "@maplibre/geojson-vt";
import { fromGeojsonVt } from "@maplibre/vt-pbf";
import type { FeatureCollection, LineString } from "geojson";

/** Synthetic integration fixture ONLY: production uses the real OpenFreeMap
 * vector source. This checks PBF decoding, WebGL rendering and local font
 * loading without misrepresenting mocked data as a live-provider test. */
async function fixtureTiles(
  page: Page,
  bounds: {
    lat_min: number;
    lat_max: number;
    lon_min: number;
    lon_max: number;
  },
) {
  const features: FeatureCollection<LineString>["features"] = [];
  for (let i = 1; i < 16; i++) {
    const lat = bounds.lat_min + ((bounds.lat_max - bounds.lat_min) * i) / 16;
    features.push({
      type: "Feature",
      properties: {
        class: i % 3 ? "minor" : "primary",
        name: `Fixture Road ${i}`,
        "name:en": `Fixture Road ${i}`,
      },
      geometry: {
        type: "LineString",
        coordinates: [
          [bounds.lon_min, lat],
          [bounds.lon_max, lat],
        ],
      },
    });
  }
  const index = new GeoJSONVT(
    { type: "FeatureCollection", features },
    { maxZoom: 14 },
  );
  await page.route("https://tiles.openfreemap.org/planet", (route) =>
    route.fulfill({
      json: {
        tilejson: "3.0.0",
        tiles: ["https://tiles.openfreemap.org/test/{z}/{x}/{y}.pbf"],
        minzoom: 0,
        maxzoom: 14,
      },
    }),
  );
  await page.route("https://tiles.openfreemap.org/test/**", (route) => {
    const match = route
      .request()
      .url()
      .match(/\/(\d+)\/(\d+)\/(\d+)\.pbf$/)!;
    const tile = index.getTile(+match[1], +match[2], +match[3]);
    return route.fulfill({
      contentType: "application/x-protobuf",
      body: Buffer.from(
        fromGeojsonVt(
          tile ? { transportation: tile, transportation_name: tile } : {},
        ),
      ),
    });
  });
}

test("vector roads render, local fonts load, and street labels can be toggled", async ({
  page,
  request,
}) => {
  const cfg = await (await request.get("/api/config")).json();
  await fixtureTiles(page, cfg.bounds);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (msg) => {
    if (
      msg.type() === "error" &&
      !msg.text().includes("Failed to load resource")
    )
      errors.push(msg.text());
  });
  const fonts: string[] = [];
  page.on("response", (response) => {
    if (response.url().endsWith(".ttf") && response.ok())
      fonts.push(response.url());
  });
  await page.goto("/");
  await expect(
    page.getByText("Street map · OpenStreetMap", { exact: true }),
  ).toBeVisible({ timeout: 25_000 });
  await expect(page.locator(".street-basemap")).toHaveCSS("opacity", "1");
  await expect(page.locator(".local-road")).toHaveCount(0);
  await expect(page.locator(".leaflet-tile")).toHaveCount(0);
  await expect(page.locator(".leaflet-control-attribution")).toContainText(
    "OpenStreetMap",
  );
  await page
    .getByRole("button", { name: "Zoom in", exact: true })
    .click({ clickCount: 3, delay: 350 });
  await expect.poll(() => fonts.length).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Map layers" }).click();
  await page.getByLabel("street names", { exact: true }).uncheck();
  await page.getByLabel("street names", { exact: true }).check();
  await page.getByRole("button", { name: "Map layers" }).click();
  await page.waitForTimeout(1000);
  expect(errors).toEqual([]);
  await page
    .locator(".map-stage")
    .screenshot({ path: "test-results/street-render-fixture.png" });
});

test("blocked streets show an explicit schematic fallback; toggles still work on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("https://tiles.openfreemap.org/**", (route) =>
    route.abort(),
  );
  await page.goto("/");
  await expect(
    page.getByText("Streets unavailable · schematic", { exact: true }),
  ).toBeVisible({ timeout: 25_000 });
  await expect(
    page.getByRole("button", { name: "Retry streets" }),
  ).toBeVisible();
  await expect(page.locator(".local-road").first()).toBeAttached();
  await expect(page.locator(".fiber-flow").first()).toBeAttached();
  await expect(page.locator(".street-basemap")).toHaveCount(0);
  await page.getByRole("button", { name: "Map layers" }).click();
  await page.getByLabel("streets", { exact: true }).uncheck();
  await expect(
    page.getByText("Local schematic", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("fiber", { exact: true }).uncheck();
  await expect(page.locator(".fiber-flow")).toHaveCount(0);
  await expect(page.locator(".local-road").first()).toBeAttached();
  await page.getByRole("button", { name: "Map layers" }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
