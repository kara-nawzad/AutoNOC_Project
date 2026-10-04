import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  BellRing,
  Check,
  ChevronRight,
  CircleCheck,
  Clock3,
  History,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { api } from "../services/api";
import type { Command, Config, Snapshot } from "../types/api";
import { Badge, Dot, PanelHeading, tone } from "./ui";

export type Execute = (
  command: Command,
  label: string,
  runId: string,
) => Promise<boolean>;
export function AlertsSidebar({
  data,
  config,
  onSelect,
  onActivity,
  execute,
}: {
  data: Snapshot;
  config: Config;
  onSelect: (id: string) => void;
  onActivity: () => void;
  execute: Execute;
}) {
  const [filter, setFilter] = useState("all");
  const [hidden, setHidden] = useState<Set<number>>(new Set());
  useEffect(() => setHidden(new Set()), [data.run_id]);
  const incidents = data.dashboard.incidents.filter(
    (a) => filter === "all" || a.severity === filter,
  );
  const pending = data.ai.pending.filter((a) => !hidden.has(a.action_id));
  async function decide(id: number, approve: boolean) {
    setHidden((old) => new Set(old).add(id));
    const ok = await execute(
      () =>
        approve ? api.approve(id, data.run_id) : api.veto(id, data.run_id),
      approve ? "Pre-dispatch approved" : "Recommendation vetoed",
      data.run_id,
    );
    if (!ok)
      setHidden((old) => {
        const next = new Set(old);
        next.delete(id);
        return next;
      });
  }
  const p = config.presentation.palette;
  return (
    <aside
      className="alerts-rail"
      id="incidents"
      aria-label="Alarms and policy recommendations"
    >
      <section className="glass alarms-panel">
        <PanelHeading
          title="Active incidents"
          right={
            <div className="heading-actions">
              <span
                className="count-badge"
                style={tone(
                  data.dashboard.current.incidents ? p.critical : p.healthy,
                )}
              >
                {data.dashboard.current.incidents}
              </span>
              <button
                className="icon-button"
                aria-label="Open event history"
                onClick={onActivity}
              >
                <History size={15} />
              </button>
            </div>
          }
        />
        <div className="rail-subhead">
          <span>
            <BellRing size={12} /> ITU-T X.733 ALARM STREAM
          </span>
          <select
            aria-label="Filter alarm severity"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">All severities</option>
            {Object.keys(config.presentation.severity_colors)
              .filter((s) => !["INFO", "CLEARED"].includes(s))
              .map((s) => (
                <option key={s}>{s}</option>
              ))}
          </select>
        </div>
        <div
          className="incident-list"
          aria-live="polite"
          aria-relevant="additions removals"
        >
          <AnimatePresence initial={false} mode="popLayout">
            {incidents.map((alarm) => (
              <motion.div
                layout
                key={alarm.id}
                className="incident"
                initial={{ opacity: 0, y: -12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: 16 }}
                transition={{ type: "spring", stiffness: 330, damping: 30 }}
              >
                <div
                  className="incident-icon"
                  style={tone(
                    config.presentation.severity_colors[alarm.severity],
                  )}
                >
                  <BellRing size={14} />
                </div>
                <div className="incident-body">
                  <div className="incident-title">
                    <strong>{alarm.title}</strong>
                    <Badge config={config} severity={alarm.severity} />
                  </div>
                  <button
                    className="incident-target"
                    disabled={!alarm.node_id}
                    onClick={() => alarm.node_id && onSelect(alarm.node_id)}
                  >
                    {alarm.node_id ?? alarm.detail}
                    {alarm.node_id && <ChevronRight size={12} />}
                  </button>
                  <div className="incident-meta">
                    <span>
                      {alarm.node_id
                        ? alarm.detail
                        : `${alarm.affected} affected sites`}
                    </span>
                    <span>
                      {alarm.dispatched
                        ? "Crew assigned"
                        : `Since t${alarm.since_tick}`}
                    </span>
                  </div>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          {!incidents.length && (
            <div className="empty-state">
              <CircleCheck size={27} style={{ color: p.healthy }} />
              <strong>
                {filter === "all" ? "Network clear" : "No matching incidents"}
              </strong>
              <span>
                {filter === "all"
                  ? "No active alarms. Monitoring every site."
                  : "Try another severity filter."}
              </span>
            </div>
          )}
        </div>
        <button className="rail-footer" onClick={onActivity}>
          <History size={12} /> View event history <ChevronRight size={13} />
        </button>
      </section>
      <section className="glass policy-panel" id="commander">
        <PanelHeading
          title="A1 Commander"
          right={
            <span className="ai-chip" style={tone(p.prediction)}>
              <Sparkles size={11} />{" "}
              {data.ai.ai_enabled ? data.ai.ai_mode.toUpperCase() : "OFF"}
            </span>
          }
        />
        <div className="policy-description">
          <ShieldCheck size={14} />
          <span>Human-approved intent. Autonomous soft mitigation.</span>
        </div>
        <div className="policy-list">
          <AnimatePresence initial={false} mode="popLayout">
            {pending.map((action) => (
              <motion.div
                layout
                className="intent-card"
                key={action.action_id}
                initial={{ opacity: 0, scale: 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, height: 0 }}
              >
                <div className="intent-top">
                  <span className="mono">{action.node_id}</span>
                  <span className="probability" style={{ color: p.prediction }}>
                    p = {action.probability.toFixed(2)}
                  </span>
                </div>
                <p>{action.label}</p>
                <div className="intent-window">
                  <Clock3 size={11} /> Risk within{" "}
                  {config.presentation.prediction_horizon_min} sim min
                  {action.eta ? ` · approval in ${Math.ceil(action.eta)}s` : ""}
                </div>
                <div className="intent-actions">
                  <button
                    onClick={() => void decide(action.action_id, true)}
                    className="approve-button"
                  >
                    <Check size={13} /> Approve pre-dispatch
                  </button>
                  <button
                    className="veto-button"
                    aria-label={`Veto action ${action.action_id}`}
                    onClick={() => void decide(action.action_id, false)}
                  >
                    <X size={13} /> Veto
                  </button>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          {!pending.length && (
            <div className="policy-empty">
              <div className="oracle-orb">
                <Sparkles size={19} />
              </div>
              <div>
                <strong>
                  {data.ai.ai_enabled
                    ? "Listening ahead of the network"
                    : "Your predictive copilot is ready"}
                </strong>
                <p>
                  {data.ai.ai_enabled
                    ? "No crew recommendations awaiting approval."
                    : "Enable AI in the header to begin forecasting."}
                </p>
              </div>
            </div>
          )}
        </div>
        <div className="policy-foot">
          <span>
            <Dot color={p.prediction} /> {data.dashboard.actionable_predictions}{" "}
            actionable forecasts
          </span>
          <span>p* {config.break_even_precision}</span>
        </div>
      </section>
    </aside>
  );
}
