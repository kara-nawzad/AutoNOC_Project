import { motion } from "framer-motion";
import { Activity, Zap } from "lucide-react";
import type { Snapshot } from "../types/api";
import { estimateIllustrativeRoi } from "../utils/roiEstimate";
import { NumberTween } from "./NumberTween";

export function RoiPill({
  data,
  onOpen,
}: {
  data: Snapshot;
  onOpen: () => void;
}) {
  const enabled = data.ai.ai_enabled;
  const estimate = estimateIllustrativeRoi(
    data.ai.pre_empted,
    data.ai.false_dispatches,
  );
  const dollars = estimate.opexSavedUsdEstimate;
  const hours = estimate.downtimeAvoidedHours;
  const description = enabled
    ? `Illustrative live ROI scenario: ${dollars < 0 ? "minus" : "plus"} ${Math.abs(dollars).toFixed(0)} US dollars and ${hours.toFixed(1)} modeled downtime hours. Click for assumptions and the paired study.`
    : "AI inactive. Click to inspect the baseline and paired counterfactual study.";

  return (
    <motion.button
      type="button"
      className={`button roi-pill ${enabled ? "active" : "inactive"}`}
      onClick={onOpen}
      title={description}
      aria-label={description}
      whileHover={{ y: -1 }}
      whileTap={{ scale: 0.98 }}
    >
      {enabled ? (
        <>
          <Zap size={13} aria-hidden="true" />
          <span className="roi-money mono">
            <span>{dollars < 0 ? "−" : "+"}$</span>
            <NumberTween
              value={Math.abs(dollars)}
              decimals={0}
              duration={850}
            />
            <small>est.</small>
          </span>
          <span className="roi-separator" aria-hidden="true">
            ·
          </span>
          <span className="roi-hours mono">
            {hours >= 0 ? "−" : "+"}
            <NumberTween value={Math.abs(hours)} decimals={1} duration={850} />h
            downtime
          </span>
        </>
      ) : (
        <>
          <Activity size={13} aria-hidden="true" />
          <span>AI Inactive · Baseline OPEX</span>
        </>
      )}
    </motion.button>
  );
}
