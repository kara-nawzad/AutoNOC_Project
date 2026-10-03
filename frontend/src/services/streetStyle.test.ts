import { describe, expect, it } from "vitest";
import { createStreetStyle, streetAttribution } from "./streetStyle";

describe("street cartography", () => {
  it("uses a vector source, not raster access-error images", () => {
    const style = createStreetStyle();
    expect(style.sources.streets.type).toBe("vector");
    expect(style.layers.some((layer) => layer.type === "raster")).toBe(false);
    expect(JSON.stringify(style)).not.toMatch(/cartocdn|tile\.openstreetmap/);
    expect(streetAttribution).toContain("OpenStreetMap");
  });
  it("includes mapped street names, buildings and zoom-dependent details", () => {
    const style = createStreetStyle();
    const names = style.layers.find((layer) => layer.id === "street-names");
    expect(names?.type).toBe("symbol");
    if (names?.type === "symbol") {
      expect(names["source-layer"]).toBe("transportation_name");
      expect(JSON.stringify(names.layout?.["text-field"])).toContain("name:en");
    }
    expect(
      style.layers.find((layer) => layer.id === "buildings")?.minzoom,
    ).toBe(13);
  });
  it("serves font files from the application's own origin", () => {
    const fonts = createStreetStyle()["font-faces"]?.["NOC Map"];
    expect(Array.isArray(fonts)).toBe(true);
    if (Array.isArray(fonts)) {
      for (const font of fonts) {
        expect(new URL(font.url).origin).toBe(window.location.origin);
      }
    }
  });
});
