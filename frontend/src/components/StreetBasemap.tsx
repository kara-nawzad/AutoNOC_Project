import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import type L from "leaflet";
import { createStreetStyle, streetAttribution } from "../services/streetStyle";

export type StreetStatus = "loading" | "ready" | "unavailable";

/** Leaflet owns all navigation/overlays; MapLibre renders only the background.
 * Readiness requires decoded, visible road geometry, not merely an HTTP 200
 * or an empty canvas. Errors cannot be rendered as raster warning images.
 * Import the WebGL engine on demand so telemetry isn't blocked by its startup. */
export default function StreetBasemap({
  names,
  onStatus,
}: {
  names: boolean;
  onStatus: (status: StreetStatus) => void;
}) {
  const map = useMap();
  const layerRef = useRef<L.MaplibreGL | null>(null);
  const namesRef = useRef(names);
  useEffect(() => {
    namesRef.current = names;
    const gl = layerRef.current?.getMaplibreMap();
    for (const id of ["street-names", "place-names", "poi-names"]) {
      if (gl?.getLayer(id))
        gl.setLayoutProperty(id, "visibility", names ? "visible" : "none");
    }
  }, [names]);

  useEffect(() => {
    let disposed = false;
    let ready = false;
    let failed = false;
    let deadline: ReturnType<typeof setTimeout>;
    onStatus("loading");
    const disposeLayer = () => {
      const layer = layerRef.current;
      layerRef.current = null;
      if (layer && map.hasLayer(layer)) map.removeLayer(layer);
      map.attributionControl?.removeAttribution(streetAttribution);
    };
    const fail = () => {
      if (disposed || failed) return;
      failed = true;
      clearTimeout(deadline);
      disposeLayer();
      onStatus("unavailable");
    };
    deadline = setTimeout(fail, 20_000);
    void Promise.all([
      import("@maplibre/maplibre-gl-leaflet"),
      import("maplibre-gl"),
      import("maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url"),
    ])
      .then(([{ maplibreGL }, engine, { default: workerUrl }]) => {
        if (disposed || failed) return;
        engine.setWorkerUrl(workerUrl);
        engine.setWorkerCount(2);
        const style = createStreetStyle();
        for (const layer of style.layers) {
          if (layer.type === "symbol")
            layer.layout = {
              ...layer.layout,
              visibility: namesRef.current ? "visible" : "none",
            };
        }
        const layer = maplibreGL({
          style,
          attributionControl: false,
          interactive: false,
        });
        layerRef.current = layer;
        layer.addTo(map);
        layer.getContainer().classList.add("street-basemap");
        // Avoid covering the schematic with a blank WebGL background while loading.
        layer.getContainer().style.opacity = "0";
        const gl = layer.getMaplibreMap();
        gl.on("render", () => {
          if (disposed || failed || ready || !gl.isStyleLoaded()) return;
          if (
            !gl.queryRenderedFeatures({ layers: ["road-minor", "road-major"] })
              .length
          )
            return;
          ready = true;
          clearTimeout(deadline);
          layer.getContainer().style.opacity = "1";
          map.attributionControl?.addAttribution(streetAttribution);
          onStatus("ready");
        });
        // A denied/corrupt initial tile source or missing WebGL is a visible
        // fallback, never success. Transient edge-tile errors retain a loaded map.
        gl.on("error", () => {
          if (!ready) queueMicrotask(fail);
        });
        gl.on("webglcontextlost", () => queueMicrotask(fail));
      })
      .catch(fail);
    return () => {
      disposed = true;
      clearTimeout(deadline);
      disposeLayer();
    };
  }, [map, onStatus]);
  return null;
}
