import { motion, AnimatePresence } from "framer-motion";
import { RadioTower, X, MapPin, Wrench, Zap, ShieldCheck } from "lucide-react";
import type { Config, NodeData } from "../types/api";
import { NumberTween } from "./NumberTween";
import { tone } from "./ui";

export function Inspector({
  node,
  config,
  onClose,
  onInject,
}: {
  node?: NodeData;
  config: Config;
  onClose: () => void;
  onInject: (id: string) => void;
}) {
  return (
    <AnimatePresence>
      {node && (
        <motion.aside
          className="inspector glass"
          key="inspector"
          aria-label={`Inspector for ${node.id}`}
          initial={{ opacity: 0, x: 28 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 28 }}
          transition={{ type: "spring", stiffness: 340, damping: 32 }}
        >
          <div className="inspector-header">
            <span className="eyebrow">
              <RadioTower size={13} /> SITE INSPECTOR
            </span>
            <button
              className="icon-button"
              aria-label="Close site inspector"
              onClick={onClose}
            >
              <X size={17} />
            </button>
          </div>
          <h2 className="mono">{node.id}</h2>
          <div className="inspector-place">
            <MapPin size={12} />
            {config.agg_sites.find((a) => a.id === node.agg)?.name}{" "}
            <span>·</span> Ring {node.ring}
          </div>
          <span
            className="severity site-status"
            style={tone(config.status_colors[node.status])}
          >
            {config.status_names[node.status]}
          </span>
          <div className="inspector-tags">
            <span>{config.presentation.generation_names[node.gen]}</span>
            {node.critical && (
              <span>
                <ShieldCheck size={12} /> Priority site
              </span>
            )}
            {node.repairing ? (
              <span>
                <Wrench size={12} /> Repairing
              </span>
            ) : node.dispatched ? (
              <span>Crew dispatched</span>
            ) : null}
          </div>
          <h3>RADIO & HARDWARE</h3>
          <div className="inspector-metrics">
            {(
              [
                ["vswr", node.vswr, ":1", 2],
                ["s11", node.s11, "dB", 1],
                ["prb", node.prb, "%", 1],
                ["cqi", node.cqi, "/15", 0],
                ["rsrp", node.rsrp, "dBm", 1],
                ["sinr", node.sinr, "dB", 1],
                ["temp", node.temp, "°C", 1],
                ["loss", node.loss, "%", 2],
              ] as [string, number, string, number][]
            ).map(([key, value, unit, decimals]) => (
              <div key={key}>
                <span>{config.metric_labels[key]}</span>
                <strong>
                  <NumberTween value={value} decimals={decimals} />
                  <small>{unit}</small>
                </strong>
              </div>
            ))}
          </div>
          <h3>
            <Zap size={12} /> SITE POWER · TYPE {node.pwr}
          </h3>
          <div className="power-architecture">
            {config.power_configs[node.pwr]}
            <span
              style={{ color: config.presentation.power_colors[node.power] }}
            >
              {node.power}
            </span>
          </div>
          {[
            { key: "battery", value: node.battery },
            { key: "fuel", value: node.fuel },
          ].map(({ key, value }) => (
            <div className="inspector-gauge" key={key}>
              <div>
                <span>{config.metric_labels[key]}</span>
                <span className="mono">{value.toFixed(1)}%</span>
              </div>
              <div className="meter-track">
                <motion.i
                  animate={{ width: `${value}%` }}
                  style={{ background: config.presentation.palette.fiber }}
                />
              </div>
            </div>
          ))}
          <p className="small-muted">
            Fuel is tank percentage; tank capacity in liters is not modeled.
          </p>
          {node.ats && (
            <div
              className="inline-warning"
              style={tone(config.presentation.palette.critical)}
            >
              ATS failure to crank · maintenance required
            </div>
          )}
          {node.warn && (
            <div
              className="inline-warning"
              style={tone(config.presentation.palette.prediction)}
            >
              Oracle warning · next {config.presentation.prediction_horizon_min}{" "}
              min
            </div>
          )}
          <button
            className="button secondary inspector-action"
            disabled={node.status !== config.presentation.healthy_status}
            onClick={() => onInject(node.id)}
          >
            <Zap size={14} /> Inject fault on this site
          </button>
          <div className="inspector-coords mono">
            {node.lat.toFixed(5)} N / {node.lon.toFixed(5)} E
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
