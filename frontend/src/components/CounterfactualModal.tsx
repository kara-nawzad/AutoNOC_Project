import { useEffect, useId, useRef } from "react";
import { motion } from "framer-motion";
import { Info, Sparkles, X } from "lucide-react";
import type { Snapshot } from "../types/api";
import {
  counterfactualDeltas,
  counterfactualStudy as study,
} from "../data/counterfactualStudy";
import { estimateIllustrativeRoi, roiAssumptions } from "../utils/roiEstimate";
import { NumberTween } from "./NumberTween";

function money(value: number) {
  return Math.round(value).toLocaleString("en-US");
}

function towerHours(minutes: number) {
  return (minutes / 60).toFixed(1);
}

export function CounterfactualModal({
  data,
  onClose,
}: {
  data: Snapshot;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const a = study.arms.A;
  const c = study.arms.C;
  const estimate = estimateIllustrativeRoi(
    data.ai.pre_empted,
    data.ai.false_dispatches,
  );

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
    };
  }, []);

  return (
    <motion.dialog
      ref={ref}
      className="dialog wide impact-dialog"
      aria-labelledby={titleId}
      initial={{ opacity: 0, y: 16, scale: 0.985 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 10, scale: 0.99 }}
      transition={{ type: "spring", stiffness: 220, damping: 25 }}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      <div className="dialog-content impact-content">
        <div className="dialog-heading impact-heading">
          <div>
            <span className="eyebrow">EXECUTIVE COUNTERFACTUAL · M7</span>
            <h2 id={titleId}>
              A1 Autonomous Intent — Economic &amp; Operational Impact
            </h2>
            <p className="impact-subtitle">
              Arm A (reactive, no AI) vs Arm C (autonomous AutoNOC) · matched
              schedules · {study.seeds} seeds × {study.simulatedDaysPerSeed}{" "}
              simulated days
            </p>
          </div>
          <button
            className="icon-button"
            aria-label="Close impact report"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>

        <section
          className="impact-live"
          aria-label="Illustrative live ROI scenario"
        >
          <div className="impact-live-heading">
            <span>
              <Sparkles size={13} /> LIVE SCENARIO ESTIMATE
            </span>
            <span className={data.ai.ai_enabled ? "live-on" : "live-off"}>
              {data.ai.ai_enabled ? "AI ACTIVE" : "AI INACTIVE"}
            </span>
          </div>
          {data.ai.ai_enabled ? (
            <div className="impact-live-values">
              <div>
                <span>Illustrative OPEX benefit</span>
                <strong className="mono">
                  {estimate.opexSavedUsdEstimate < 0 ? "−$" : "+$"}
                  <NumberTween
                    value={Math.abs(estimate.opexSavedUsdEstimate)}
                    decimals={0}
                  />
                </strong>
              </div>
              <div>
                <span>Modeled downtime avoided</span>
                <strong className="mono">
                  {estimate.downtimeAvoidedHours < 0 ? "+" : "−"}
                  <NumberTween
                    value={Math.abs(estimate.downtimeAvoidedHours)}
                    decimals={1}
                  />
                  <small> h</small>
                </strong>
              </div>
              <div>
                <span>Live counters · pre-emptions / false dispatches</span>
                <strong className="mono">
                  {data.ai.pre_empted.toLocaleString("en-US")} /{" "}
                  {data.ai.false_dispatches.toLocaleString("en-US")}
                </strong>
              </div>
            </div>
          ) : (
            <p className="impact-live-inactive">
              AI is off. The live scenario counter is inactive; the paired M7
              study below remains available for comparison.
            </p>
          )}
        </section>

        <div className="impact-table-wrap">
          <table className="impact-table">
            <thead>
              <tr>
                <th scope="col">Metric</th>
                <th scope="col">Arm A · No AI</th>
                <th scope="col">Arm C · AutoNOC AI</th>
                <th scope="col">Difference (C vs A)</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Network availability</th>
                <td>
                  {a.availabilityPct.toFixed(2)}% ±{" "}
                  {a.availabilityCi95.toFixed(2)}
                </td>
                <td>
                  {c.availabilityPct.toFixed(2)}% ±{" "}
                  {c.availabilityCi95.toFixed(2)}
                </td>
                <td className="positive">
                  +
                  {counterfactualDeltas.availabilityPercentagePoints.toFixed(2)}{" "}
                  percentage points
                </td>
              </tr>
              <tr>
                <th scope="row">Aggregate tower downtime</th>
                <td>{towerHours(a.downtimeTowerMinutes)} tower-hours</td>
                <td>{towerHours(c.downtimeTowerMinutes)} tower-hours</td>
                <td className="positive">
                  −{towerHours(counterfactualDeltas.downtimeTowerMinutes)} h (
                  {counterfactualDeltas.downtimeTowerMinutes.toLocaleString(
                    "en-US",
                  )}{" "}
                  tower-min)
                </td>
              </tr>
              <tr>
                <th scope="row">Pre-empted episodes · mean</th>
                <td>{a.preemptedEpisodes.toFixed(1)}</td>
                <td>{c.preemptedEpisodes.toFixed(1)}</td>
                <td>+{c.preemptedEpisodes.toFixed(1)} episodes</td>
              </tr>
              <tr>
                <th scope="row">False dispatches · mean</th>
                <td>{a.falseDispatches.toFixed(1)}</td>
                <td>{c.falseDispatches.toFixed(1)}</td>
                <td className="caution">
                  +{c.falseDispatches.toFixed(1)} false dispatches
                </td>
              </tr>
              <tr>
                <th scope="row">Crew fleet-occupation</th>
                <td>
                  {a.crewHours.toFixed(1)} ± {a.crewHoursCi95.toFixed(1)} h
                </td>
                <td>
                  {c.crewHours.toFixed(1)} ± {c.crewHoursCi95.toFixed(1)} h
                </td>
                <td className="caution">
                  +{counterfactualDeltas.crewHours.toFixed(1)} h used · not
                  saved
                </td>
              </tr>
              <tr>
                <th scope="row">M7 cost-model proxy</th>
                <td>{money(a.costTowerMinutes)} tower-min units</td>
                <td>{money(c.costTowerMinutes)} tower-min units</td>
                <td className="positive">
                  {money(counterfactualDeltas.costTowerMinutes)} units lower ·
                  18.6%
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <blockquote className="impact-callout">
          “Autonomous A1 captured {study.clairvoyantDowntimeHeadroomCapturedPct}
          % of the clairvoyant downtime-reduction headroom in this study. The
          tested advisory arm was indistinguishable from no-AI: its human
          approval latency erased the predictive advantage.”
        </blockquote>

        <div className="impact-notes">
          <p>
            <Info size={14} />
            <span>
              <strong>Study basis.</strong> Values are mean outcomes over{" "}
              {study.seeds}
              matched seeds and {study.simulatedDaysPerSeed} simulated days per
              seed, not monthly projections. Tower-hours aggregate downtime
              across sites. The M7 cost proxy uses fixed simulation weights (90
              per activated episode, 45 per pre-emption, 35 per false dispatch);
              it is not USD.
            </span>
          </p>
          <p>
            <Info size={14} />
            <span>
              <strong>Live dollar scenario is illustrative only.</strong> It
              applies the supplied assumptions:{" "}
              {roiAssumptions.averageRepairHoursPerPreemption} h per
              pre-emption, {roiAssumptions.travelHoursPerFalseDispatch} h per
              false dispatch, ${roiAssumptions.slaPenaltyUsdPerDowntimeHour}
              /downtime-hour, and ${roiAssumptions.truckRollCostUsd}/assumed
              truck roll. It assumes one avoided roll per pre-emption, less
              false dispatches. The backend does not measure these prices or a
              paired live no-AI outcome.
            </span>
          </p>
        </div>
      </div>
    </motion.dialog>
  );
}
