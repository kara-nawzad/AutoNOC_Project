import { motion } from "framer-motion";
import { ArrowUpRight, Sparkles, Truck, Zap } from "lucide-react";
import type { Config, Snapshot } from "../types/api";
import { NumberTween } from "./NumberTween";
import { Dot, PanelHeading } from "./ui";
import { TrafficQualityCard } from "./TrafficQualityCard";

export function AnalyticsRow({
  data,
  config,
  onSelect,
  onFleet,
}: {
  data: Snapshot;
  config: Config;
  onSelect: (id: string) => void;
  onFleet: () => void;
}) {
  const { top_cells: top, forecast, power, fleet } = data.dashboard;
  const p = config.presentation.palette;
  let offset = 0;
  return (
    <section
      className="analytics-grid"
      id="analytics"
      aria-label="Telemetry and root-cause analytics"
    >
      <TrafficQualityCard data={data} config={config} />
      <article className="glass analytics-card cells-card">
        <PanelHeading
          title="Radio load watch"
          right={<span className="small-muted">TOP {top.length}</span>}
        />
        <div className="cell-table-head">
          <span>SITE / DISTRICT</span>
          <span>PRB</span>
          <span>CQI</span>
        </div>
        {top.map((cell) => (
          <button
            key={cell.node_id}
            className="cell-row"
            onClick={() => onSelect(cell.node_id)}
          >
            <span>
              <strong className="mono">
                {cell.node_id}
                <ArrowUpRight size={11} />
              </strong>
              <small>{cell.district}</small>
            </span>
            <span className="cell-load">
              <span className="mono">{cell.prb.toFixed(0)}%</span>
              <span className="load-bar">
                <motion.i
                  animate={{ width: `${cell.prb}%` }}
                  style={{ background: config.status_colors[cell.status] }}
                />
              </span>
            </span>
            <span className="cqi mono">{cell.cqi}</span>
          </button>
        ))}
        <p className="analytics-foot">
          Ranked by utilization · select a site to investigate
        </p>
      </article>
      <article className="glass analytics-card oracle-card">
        <PanelHeading
          title="Oracle outlook"
          right={<Sparkles size={15} style={{ color: p.prediction }} />}
        />
        <div className="radial-wrap">
          <svg viewBox="0 0 180 154" aria-hidden="true">
            <circle
              cx="90"
              cy="85"
              r="64"
              fill="none"
              stroke="rgba(139,92,246,.08)"
              strokeWidth="12"
              pathLength="100"
              strokeDasharray="75 25"
              transform="rotate(135 90 85)"
              strokeLinecap="round"
            />
            <motion.circle
              cx="90"
              cy="85"
              r="64"
              fill="none"
              stroke={p.prediction}
              strokeWidth="7"
              pathLength="100"
              initial={false}
              animate={{
                strokeDasharray: `${(forecast?.probability ?? 0) * 75} 100`,
              }}
              transform="rotate(135 90 85)"
              strokeLinecap="round"
              transition={{ type: "spring", stiffness: 90, damping: 22 }}
            />
            <line
              x1="148"
              x2="161"
              y1="85"
              y2="85"
              stroke={p.warning}
              strokeWidth="2"
              transform={`rotate(${135 + config.break_even_precision * 270} 90 85)`}
            />
          </svg>
          <div className="radial-value">
            {forecast ? (
              <>
                <NumberTween value={forecast.probability * 100} decimals={1} />
                <small>%</small>
              </>
            ) : (
              <span>—</span>
            )}
            <p>{data.ai.ai_enabled ? "HIGHEST SITE RISK" : "AI IS DISABLED"}</p>
          </div>
        </div>
        <div className="oracle-target">
          <span className="mono">
            {forecast?.node_id ?? "Awaiting predictions"}
          </span>
          <span>Next {config.presentation.prediction_horizon_min} sim min</span>
        </div>
        <div className="oracle-threshold">
          <Dot color={p.warning} /> Action threshold{" "}
          <span className="mono">p &gt; {config.break_even_precision}</span>
        </div>
      </article>
      <article className="glass analytics-card power-card">
        <PanelHeading
          title="Site power & fleet"
          right={<Zap size={15} style={{ color: p.warning }} />}
        />
        <div className="power-chart-row">
          <div className="donut-wrap">
            <svg
              viewBox="0 0 112 112"
              aria-label="Current site power-source distribution"
              role="img"
            >
              <circle
                cx="56"
                cy="56"
                r="43"
                fill="none"
                stroke="rgba(255,255,255,.035)"
                strokeWidth="10"
              />
              {power.map((source) => {
                const start = offset;
                offset += source.fraction * 100;
                return (
                  <motion.circle
                    key={source.name}
                    cx="56"
                    cy="56"
                    r="43"
                    fill="none"
                    stroke={config.presentation.power_colors[source.name]}
                    strokeWidth="10"
                    pathLength="100"
                    transform="rotate(-90 56 56)"
                    initial={false}
                    animate={{
                      strokeDasharray: `${Math.max(0, source.fraction * 100 - (source.fraction === 1 ? 0 : 1.2))} 100`,
                      strokeDashoffset: -start,
                    }}
                    transition={{ type: "spring", stiffness: 100, damping: 24 }}
                  />
                );
              })}
            </svg>
            <div>
              <strong>
                <NumberTween value={config.num_nodes} />
              </strong>
              <small>POWER PLANTS</small>
            </div>
          </div>
          <div className="power-legend">
            {power.map((source) => (
              <span key={source.name}>
                <Dot color={config.presentation.power_colors[source.name]} />
                {source.name === "Generator" ? "Diesel DG" : source.name}
                <b className="mono">{source.count}</b>
              </span>
            ))}
          </div>
        </div>
        <div className="power-ats">
          <span>Active ATS alarms</span>
          <strong
            style={{
              color: data.dashboard.active_ats ? p.critical : p.healthy,
            }}
          >
            {data.dashboard.active_ats}
          </strong>
        </div>
        <button className="fleet-summary" onClick={onFleet}>
          <span>
            <Truck size={14} /> Maintenance fleet
          </span>
          <span>
            <b>{fleet.IDLE}</b> available / {config.num_teams}
            <ArrowUpRight size={13} />
          </span>
        </button>
      </article>
    </section>
  );
}
