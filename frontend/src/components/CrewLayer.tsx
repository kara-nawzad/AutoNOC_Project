import { useEffect, useMemo, useRef } from "react";
import { useMap } from "react-leaflet";
import { useReducedMotion } from "framer-motion";
import L from "leaflet";
import type { Config, Snapshot } from "../types/api";
import { CrewMotion } from "../services/crewMotion";

/** Leaflet rounds latLngToLayerPoint to integer pixels. Keep its normal marker
 * lifecycle/zoom handling but use fractional translation during RAF movement;
 * otherwise a slow-moving truck visibly hops one pixel at a time. */
export class SubpixelCrewMarker extends L.Marker {
  override setLatLng(latlng: L.LatLngExpression): this {
    super.setLatLng(latlng);
    const element = this.getElement();
    if (element && this._map) {
      const point = this._map
        .project(this.getLatLng())
        .subtract(this._map.getPixelOrigin());
      L.DomUtil.setPosition(element, point);
    }
    return this;
  }
}

/** One RAF for the fleet; React and tooltips update only on received snapshots.
 * Clock ownership stays on the server; all destinations are confirmed samples. */
export function CrewLayer({
  data,
  config,
}: {
  data: Snapshot;
  config: Config;
}) {
  const map = useMap();
  const reduced = useReducedMotion();
  const motion = useMemo(
    () => new CrewMotion(config.presentation.poll_ms),
    [config],
  );
  const markers = useRef(new Map<number, L.Marker>());

  useEffect(() => {
    const now = performance.now();
    motion.push(
      {
        runId: data.run_id,
        tick: data.tick,
        paused: data.control.paused,
        teams: data.teams,
      },
      now,
      !!reduced || document.hidden,
    );
    const ids = new Set<number>();
    for (const team of data.teams) {
      ids.add(team.id);
      let marker = markers.current.get(team.id);
      if (!marker) {
        const vehicle = document.createElement("div");
        vehicle.className = "crew-marker";
        vehicle.style.color = config.presentation.palette.crew;
        // Static SVG only; server-provided names below always use textContent.
        vehicle.innerHTML =
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 6h11v11H3zM14 10h4l3 4v3h-7"/><circle cx="7" cy="18" r="2" fill="currentColor"/><circle cx="18" cy="18" r="2" fill="currentColor"/></svg>';
        marker = new SubpixelCrewMarker(motion.position(team.id, now)!, {
          icon: L.divIcon({
            className: "crew-wrapper",
            html: vehicle,
            iconSize: [27, 27],
            iconAnchor: [13, 13],
          }),
          zIndexOffset: 800,
        }).addTo(map);
        marker.bindTooltip("", { className: "network-tooltip" });
        marker.getElement()!.dataset.crewId = String(team.id);
        markers.current.set(team.id, marker);
      }
      const text = `${team.name} · ${team.state.replaceAll("_", " ")} · ETA ${team.eta} ticks`;
      if (marker.options.title !== text) {
        const content = document.createElement("span");
        content.textContent = text;
        marker.setTooltipContent(content);
        marker.options.title = text;
        marker.getElement()?.setAttribute("aria-label", text);
      }
      marker.getElement()?.classList.toggle("crew-idle", team.available);
    }
    for (const [id, marker] of markers.current) {
      if (!ids.has(id)) {
        marker.remove();
        markers.current.delete(id);
      }
    }
  }, [map, data, config, motion, reduced]);

  useEffect(() => {
    let frame = 0;
    const fleet = markers.current;
    const onVisibility = () => motion.settle();
    document.addEventListener("visibilitychange", onVisibility);
    function draw(now: number) {
      if (!document.hidden) {
        for (const [id, marker] of fleet) {
          const position = motion.position(id, now);
          const previous = marker.getLatLng();
          if (
            position &&
            (position[0] !== previous.lat || position[1] !== previous.lng)
          )
            marker.setLatLng(position);
        }
      }
      frame = requestAnimationFrame(draw);
    }
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", onVisibility);
      fleet.forEach((marker) => marker.remove());
      fleet.clear();
    };
  }, [map, motion]);
  return null;
}
