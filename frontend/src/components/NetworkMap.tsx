import { memo, useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  Pane,
  CircleMarker,
  Polyline,
  Tooltip,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import { useReducedMotion } from "framer-motion";
import {
  Layers3,
  LocateFixed,
  Minus,
  Plus,
  Maximize2,
  CloudLightning,
  MapPin,
} from "lucide-react";
import type { Config, NodeData, Snapshot } from "../types/api";
import { Dot, PanelHeading, tone } from "./ui";
import { CrewLayer } from "./CrewLayer";
import StreetBasemap, { type StreetStatus } from "./StreetBasemap";

/** Self-contained geographic schematic: only the engine's existing road
 * corridors are drawn. There are deliberately no remote image tiles, API keys,
 * fabricated streets or inferred district boundaries. A dedicated lower pane
 * keeps these reference routes behind the live operational overlays. */
function LocalBasemap({ config }: { config: Config }) {
  const renderer = useMemo(
    () => L.svg({ pane: "local-basemap", padding: 0.4 }),
    [],
  );
  return (
    <Pane name="local-basemap" style={{ zIndex: 250 }}>
      {config.presentation.roads.map((road) => (
        <Polyline
          key={road.name}
          positions={road.path}
          renderer={renderer}
          className="local-road-casing"
          interactive={false}
          pathOptions={{
            color: config.presentation.palette.muted,
            weight: 7,
            opacity: 0.12,
          }}
        />
      ))}
      {config.presentation.roads.map((road) => (
        <Polyline
          key={road.name}
          positions={road.path}
          renderer={renderer}
          className="local-road"
          pathOptions={{
            color: config.presentation.palette.muted,
            weight: 2,
            opacity: 0.65,
          }}
        >
          <Tooltip className="network-tooltip" sticky>
            {road.name} · schematic corridor
          </Tooltip>
        </Polyline>
      ))}
    </Pane>
  );
}

const Towers = memo(function Towers({
  nodes,
  config,
  onSelect,
}: {
  nodes: NodeData[];
  config: Config;
  onSelect: (id: string) => void;
}) {
  const renderer = useMemo(() => L.canvas({ padding: 0.3 }), []);
  return (
    <>
      {nodes.map((node) => {
        const color = node.warn
          ? config.presentation.palette.prediction
          : config.status_colors[node.status];
        const active =
          node.warn || node.status !== config.presentation.healthy_status;
        return (
          <CircleMarker
            key={node.id}
            center={[node.lat, node.lon]}
            renderer={renderer}
            radius={active ? 7 : 5}
            pathOptions={{
              color,
              fillColor: color,
              fillOpacity: 0.92,
              weight: active ? 10 : 6,
              opacity: active ? 0.22 : 0.12,
            }}
            eventHandlers={{ click: () => onSelect(node.id) }}
          >
            <Tooltip
              className="network-tooltip"
              direction="top"
              offset={[0, -5]}
            >
              <strong>{node.id}</strong>
              <br />
              {config.status_names[node.status]}
              <br />
              {config.metric_labels.vswr} {node.vswr.toFixed(2)} ·{" "}
              {config.metric_labels.prb} {node.prb.toFixed(1)}%
            </Tooltip>
          </CircleMarker>
        );
      })}
    </>
  );
});

function MapTools({
  config,
  selected,
  district,
  resetKey,
}: {
  config: Config;
  selected?: NodeData;
  district: number | null;
  resetKey: number;
}) {
  const map = useMap();
  const reduced = useReducedMotion();
  useEffect(() => {
    const scale = L.control
      .scale({ position: "bottomright", imperial: false, maxWidth: 80 })
      .addTo(map);
    return () => {
      scale.remove();
    };
  }, [map]);
  useEffect(() => {
    const observer = new ResizeObserver(() =>
      map.invalidateSize({ pan: false }),
    );
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);
  useEffect(() => {
    const b = config.bounds;
    map.fitBounds(
      [
        [b.lat_min, b.lon_min],
        [b.lat_max, b.lon_max],
      ],
      { padding: [15, 15], animate: false },
    );
  }, [map, config, resetKey]);
  useEffect(() => {
    if (selected)
      map.flyTo(
        [selected.lat, selected.lon],
        Math.max(map.getZoom(), config.map_zoom + 1),
        { duration: reduced ? 0 : 0.85 },
      );
    // Telemetry updates must not re-center the viewport every second.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, selected?.id, reduced, config.map_zoom]);
  useEffect(() => {
    if (district !== null) {
      const site = config.agg_sites.find((s) => s.id === district);
      if (site)
        map.flyTo([site.lat, site.lon], config.map_zoom + 1, {
          duration: reduced ? 0 : 0.85,
        });
    }
  }, [map, config, district, reduced]);
  return (
    <div className="map-zoom" onMouseDown={(e) => e.stopPropagation()}>
      <button aria-label="Zoom in" onClick={() => map.zoomIn()}>
        <Plus size={16} />
      </button>
      <button aria-label="Zoom out" onClick={() => map.zoomOut()}>
        <Minus size={16} />
      </button>
    </div>
  );
}

export function NetworkMap({
  config,
  data,
  selectedId,
  onSelect,
}: {
  config: Config;
  data: Snapshot;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const svgRenderer = useMemo(() => L.svg({ padding: 0.4 }), []);
  const [layers, setLayers] = useState({
    sites: true,
    fiber: true,
    crews: true,
    districts: true,
    streets: true,
    "street names": true,
  });
  const [layerMenu, setLayerMenu] = useState(false);
  const [streetStatus, setStreetStatus] = useState<StreetStatus>("loading");
  const [streetAttempt, setStreetAttempt] = useState(0);
  const [district, setDistrict] = useState<number | null>(null);
  const [resetKey, setResetKey] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const p = config.presentation.palette;
  const selected = data.nodes.find((n) => n.id === selectedId);
  const storm = data.agg.find((a) => a.weather === "Storm");
  const b = config.bounds;
  return (
    <section
      ref={ref}
      id="network"
      className={`glass map-panel ${expanded ? "map-expanded" : ""}`}
      aria-label="Live network map"
    >
      <PanelHeading
        title="Network topology"
        right={
          <div className="map-heading-right">
            <Dot color={p.healthy} pulse={!data.control.paused} />
            <span>LIVE NETWORK</span>
            <span className="divider" />
            <span className="mono">{config.num_nodes} SITES</span>
          </div>
        }
      />
      <div className="map-stage">
        <MapContainer
          center={config.map_center}
          zoom={config.map_zoom}
          minZoom={config.map_zoom - 2}
          maxZoom={19}
          maxBounds={L.latLngBounds([
            [b.lat_min, b.lon_min],
            [b.lat_max, b.lon_max],
          ]).pad(0.8)}
          zoomSnap={0.1}
          zoomDelta={0.5}
          zoomControl={false}
          attributionControl
          scrollWheelZoom
        >
          {(!layers.streets || streetStatus !== "ready") && (
            <LocalBasemap config={config} />
          )}
          {layers.streets && (
            <StreetBasemap
              key={streetAttempt}
              names={layers["street names"]}
              onStatus={setStreetStatus}
            />
          )}
          {layers.fiber &&
            data.rings.map((r) => (
              <Polyline
                key={r.id}
                positions={r.path}
                renderer={svgRenderer}
                className="fiber-flow"
                pathOptions={{
                  color: p.fiber,
                  weight: 1.3,
                  opacity: 0.48,
                  dashArray: "5 7",
                }}
              />
            ))}
          {layers.fiber &&
            data.rings.flatMap((r) =>
              r.cuts.map((c, index) => (
                <Polyline
                  key={`${r.id}-${index}`}
                  renderer={svgRenderer}
                  className="cut-segment"
                  positions={
                    c.path ?? [
                      [c.lat, c.lon],
                      [c.lat, c.lon],
                    ]
                  }
                  pathOptions={{
                    color: r.isolated ? p.critical : p.warning,
                    weight: 3,
                    opacity: 0.95,
                  }}
                />
              )),
            )}
          {layers.sites && (
            <Towers nodes={data.nodes} config={config} onSelect={onSelect} />
          )}
          {layers.sites &&
            data.nodes
              .filter((n) => n.warn)
              .map((n) => (
                <CircleMarker
                  key={`prediction-${n.id}`}
                  center={[n.lat, n.lon]}
                  radius={13}
                  renderer={svgRenderer}
                  className="predictive-pulse"
                  interactive={false}
                  pathOptions={{
                    color: p.prediction,
                    fillOpacity: 0,
                    weight: 1.4,
                  }}
                />
              ))}
          {layers.districts &&
            data.agg.map((a) => (
              <CircleMarker
                key={a.id}
                center={[a.lat, a.lon]}
                radius={2}
                pathOptions={{ opacity: 0.5, color: p.fiber, fillOpacity: 0.8 }}
                interactive={false}
              >
                <Tooltip
                  permanent
                  direction="top"
                  offset={[0, -4]}
                  className="district-label"
                >
                  {a.name}
                </Tooltip>
              </CircleMarker>
            ))}
          {layers.fiber &&
            data.rings.flatMap((r) =>
              r.cuts.map((c, i) => (
                <CircleMarker
                  key={`cut-${r.id}-${i}`}
                  renderer={svgRenderer}
                  className="cut-pulse"
                  center={[c.lat, c.lon]}
                  radius={10}
                  pathOptions={{
                    color: r.isolated ? p.critical : p.warning,
                    weight: 2,
                    fillOpacity: 0.22,
                  }}
                >
                  <Tooltip className="network-tooltip">
                    {c.seg} · {c.cause} ·{" "}
                    {r.isolated ? "Isolated" : "Unprotected"}
                  </Tooltip>
                </CircleMarker>
              )),
            )}
          {selected && (
            <CircleMarker
              center={[selected.lat, selected.lon]}
              radius={13}
              pathOptions={{ color: p.crew, weight: 1.5, fillOpacity: 0 }}
              interactive={false}
            />
          )}
          {layers.crews && <CrewLayer data={data} config={config} />}
          <MapTools
            config={config}
            selected={selected}
            district={district}
            resetKey={resetKey}
          />
        </MapContainer>
        <div className="map-top-overlay">
          <select
            aria-label="Focus district"
            value={district ?? ""}
            onChange={(e) => {
              setDistrict(
                e.target.value === "" ? null : Number(e.target.value),
              );
              if (!e.target.value) setResetKey((k) => k + 1);
            }}
          >
            <option value="">All districts</option>
            {config.agg_sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <div className="layer-control">
            <button
              className={`map-button ${layerMenu ? "active" : ""}`}
              aria-expanded={layerMenu}
              aria-label="Map layers"
              onClick={() => setLayerMenu((v) => !v)}
            >
              <Layers3 size={15} />
            </button>
            {layerMenu && (
              <div className="layer-menu">
                {Object.entries(layers).map(([key, value]) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={value}
                      onChange={() =>
                        setLayers((v) => ({ ...v, [key]: !value }))
                      }
                    />
                    {key}
                  </label>
                ))}
              </div>
            )}
            <button
              className="map-button"
              aria-label="Reset map view"
              onClick={() => {
                setDistrict(null);
                setResetKey((k) => k + 1);
              }}
            >
              <LocateFixed size={15} />
            </button>
            <button
              className="map-button"
              aria-label={expanded ? "Exit expanded map" : "Expand map"}
              onClick={() => setExpanded((v) => !v)}
            >
              <Maximize2 size={15} />
            </button>
          </div>
        </div>
        <div className="map-location">
          <MapPin size={12} /> {config.presentation.network_name.toUpperCase()}{" "}
          <span> / </span> {config.presentation.region_label}
        </div>
        {storm && (
          <div className="weather-chip" style={tone(p.warning)}>
            <CloudLightning size={15} />
            <div>
              <strong>{storm.name}</strong>
              <span>
                {storm.weather} · {storm.wind} km/h
              </span>
            </div>
          </div>
        )}
        <div className="map-mode" aria-live="polite">
          <span aria-hidden="true" />
          <span className="map-mode-label">
            {!layers.streets
              ? "Local schematic"
              : streetStatus === "ready"
                ? "Street map · OpenStreetMap"
                : streetStatus === "loading"
                  ? "Loading streets…"
                  : "Streets unavailable · schematic"}
          </span>
          {layers.streets && streetStatus === "unavailable" && (
            <button
              type="button"
              onClick={() => setStreetAttempt((n) => n + 1)}
            >
              Retry streets
            </button>
          )}
        </div>
        <div className="map-north" aria-label="North is up">
          <span>N</span>
          <span aria-hidden="true">↑</span>
        </div>
      </div>
      <div className="map-footer">
        <div className="map-legend">
          {Object.entries(config.status_names).map(([id, name]) => (
            <span key={id}>
              <Dot color={config.status_colors[Number(id)]} />
              {name}
            </span>
          ))}
        </div>
        <span className="map-footer-hint">
          Select a site to inspect <span>↗</span>
        </span>
      </div>
    </section>
  );
}
