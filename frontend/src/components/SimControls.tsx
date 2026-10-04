import { useEffect, useState } from "react";
import {
  Pause,
  Play,
  StepForward,
  Scissors,
  Zap,
  Sparkles,
  Gauge,
  ChevronDown,
  Check,
} from "lucide-react";
import type { Config, Snapshot } from "../types/api";
import type { Execute } from "./AlertsSidebar";
import { api } from "../services/api";
import { Modal } from "./ui";

export function SimControls({
  data,
  config,
  busy,
  execute,
  onCut,
  onInject,
}: {
  data: Snapshot;
  config: Config;
  busy: boolean;
  execute: Execute;
  onCut: () => void;
  onInject: () => void;
}) {
  const [speedOpen, setSpeedOpen] = useState(false);
  const [draft, setDraft] = useState(data.control.speed);
  useEffect(() => setDraft(data.control.speed), [data.control.speed]);
  return (
    <div className="sim-controls">
      <div className="play-controls">
        <button
          className="icon-button"
          disabled={busy}
          aria-label={
            data.control.paused ? "Resume simulation" : "Pause simulation"
          }
          title={data.control.paused ? "Resume" : "Pause"}
          onClick={() =>
            void execute(
              () =>
                data.control.paused
                  ? api.resume(data.run_id)
                  : api.pause(data.run_id),
              data.control.paused ? "Simulation resumed" : "Simulation paused",
              data.run_id,
            )
          }
        >
          {data.control.paused ? <Play size={15} /> : <Pause size={15} />}
        </button>
        <button
          className="icon-button"
          disabled={busy || !data.control.paused}
          aria-label="Advance one simulation tick"
          title="Single step (pause first)"
          onClick={() =>
            void execute(
              () => api.step(data.run_id),
              "Advanced one simulation tick",
              data.run_id,
            )
          }
        >
          <StepForward size={15} />
        </button>
      </div>
      <div className="speed-control">
        <button
          className="speed-button"
          aria-expanded={speedOpen}
          onClick={() => setSpeedOpen((v) => !v)}
        >
          <Gauge size={13} />
          <span className="mono">{data.control.speed}×</span>
          <ChevronDown size={12} />
        </button>
        {speedOpen && (
          <div className="speed-popover">
            <label htmlFor="speed">
              Simulation speed <span>{draft}×</span>
            </label>
            <input
              id="speed"
              type="range"
              min={config.presentation.speed_min}
              max={config.presentation.speed_max}
              step={0.25}
              value={draft}
              onChange={(e) => setDraft(Number(e.target.value))}
            />
            <div className="speed-range">
              <span>{config.presentation.speed_min}×</span>
              <span>{config.presentation.speed_max}×</span>
            </div>
            <button
              className="button secondary"
              disabled={busy}
              onClick={() =>
                void execute(
                  () => api.speed(draft, data.run_id),
                  `Speed set to ${draft}×`,
                  data.run_id,
                ).then((ok) => {
                  if (ok) setSpeedOpen(false);
                })
              }
            >
              <Check size={13} /> Apply speed
            </button>
          </div>
        )}
      </div>
      <span className="control-separator" />
      <button
        className="button scenario-button"
        disabled={busy}
        onClick={onCut}
      >
        <Scissors size={14} />
        <span>Cut fiber</span>
      </button>
      <button
        className="button scenario-button"
        disabled={busy}
        onClick={onInject}
      >
        <Zap size={14} />
        <span>Inject fault</span>
      </button>
      <button
        className={`button ai-toggle ${data.ai.ai_enabled ? "enabled" : ""}`}
        disabled={busy}
        onClick={() =>
          void execute(
            () => api.ai(!data.ai.ai_enabled, data.run_id),
            data.ai.ai_enabled ? "AI disabled" : "AI enabled",
            data.run_id,
          )
        }
        aria-pressed={data.ai.ai_enabled}
        title="Enable the loaded ML predictor, or its automatic fallback; crew actions still require approval"
      >
        <Sparkles size={14} />
        <span>AI {data.ai.ai_enabled ? "enabled" : "disabled"}</span>
        <span className="toggle-track">
          <i />
        </span>
      </button>
    </div>
  );
}

export function ScenarioModal({
  type,
  initialNode,
  data,
  config,
  execute,
  onClose,
}: {
  type: "inject" | "cut";
  initialNode?: string;
  data: Snapshot;
  config: Config;
  execute: Execute;
  onClose: () => void;
}) {
  const candidates = data.nodes.filter(
    (n) => n.status === config.presentation.healthy_status,
  );
  const [node, setNode] = useState(initialNode ?? candidates[0]?.id ?? "");
  const [kind, setKind] = useState(config.presentation.fault_options[0].value);
  const [ring, setRing] = useState(data.rings[0]?.id ?? 0);
  const [pending, setPending] = useState(false);
  async function submit() {
    setPending(true);
    const ok = await execute(
      () =>
        type === "cut"
          ? api.cut(ring, data.run_id)
          : api.inject(node, kind, data.run_id),
      type === "cut"
        ? `Double cut requested on ring ${ring}`
        : `Fault injected on ${node}`,
      data.run_id,
    );
    setPending(false);
    if (ok) onClose();
  }
  return (
    <Modal
      title={
        type === "cut" ? "Fiber isolation scenario" : "Inject a site fault"
      }
      onClose={onClose}
    >
      <p className="dialog-intro">
        {type === "cut"
          ? "Create a double cut on a protected ring. Watch correlated alarms and maintenance dispatch respond to the same event."
          : "Introduce a supported fault into the live simulation. This is a shared world: every connected operator will see the event."}
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {type === "cut" ? (
          <label className="field">
            Fiber ring
            <select
              value={ring}
              onChange={(e) => setRing(Number(e.target.value))}
            >
              {data.rings.map((r) => (
                <option key={r.id} value={r.id}>
                  Ring {r.id.toString().padStart(2, "0")} · {r.nodes.length}{" "}
                  sites · {r.cuts.length} open cuts
                </option>
              ))}
            </select>
          </label>
        ) : (
          <>
            <label className="field">
              Site
              <select
                value={node}
                onChange={(e) => setNode(e.target.value)}
                required
              >
                {candidates.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.id} ·{" "}
                    {config.agg_sites.find((a) => a.id === n.agg)?.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Fault class
              <select
                value={kind}
                onChange={(e) => setKind(Number(e.target.value))}
              >
                {config.presentation.fault_options.map((f) => (
                  <option key={f.value} value={f.value}>
                    {f.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="small-muted">
              Dust, ATS, and fuel theft follow the engine's dynamics. They are
              not separate injectable classes.
            </p>
          </>
        )}
        <div className="scenario-disclaimer">
          <Zap size={15} />
          <span>
            Simulation only · no real network equipment is controlled.
          </span>
        </div>
        <div className="dialog-actions">
          <button type="button" className="button secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="button primary"
            disabled={pending || (type === "inject" && !node)}
          >
            {pending
              ? "Sending command…"
              : type === "cut"
                ? "Confirm double cut"
                : "Inject fault"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
