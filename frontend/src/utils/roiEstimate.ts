/**
 * Explicitly illustrative scenario assumptions supplied for the executive ROI
 * view. These are not M6/M7 cost-engine values and are not actual invoices.
 * The live engine does not measure contract penalties or diesel/labor rates.
 */
export const roiAssumptions = {
  averageRepairHoursPerPreemption: 4.2,
  travelHoursPerFalseDispatch: 0.5,
  slaPenaltyUsdPerDowntimeHour: 120,
  truckRollCostUsd: 180,
} as const;

export interface RoiEstimate {
  downtimeAvoidedHours: number;
  truckRollsSavedAssumed: number;
  opexSavedUsdEstimate: number;
}

/**
 * Applies the user-provided assumptions to current-run counters only.
 * It assumes one avoided truck roll per pre-empted episode and one wasted roll
 * per false dispatch; saved rolls are floored at zero. This is a scenario
 * estimate, not a paired AI-off counterfactual or measured financial saving.
 */
export function estimateIllustrativeRoi(
  preemptedEpisodes: number,
  falseDispatches: number,
): RoiEstimate {
  const preempted = Math.max(
    0,
    Number.isFinite(preemptedEpisodes) ? preemptedEpisodes : 0,
  );
  const falseCount = Math.max(
    0,
    Number.isFinite(falseDispatches) ? falseDispatches : 0,
  );
  const downtimeAvoidedHours =
    preempted * roiAssumptions.averageRepairHoursPerPreemption -
    falseCount * roiAssumptions.travelHoursPerFalseDispatch;
  const truckRollsSavedAssumed = Math.max(0, preempted - falseCount);
  const opexSavedUsdEstimate =
    downtimeAvoidedHours * roiAssumptions.slaPenaltyUsdPerDowntimeHour +
    truckRollsSavedAssumed * roiAssumptions.truckRollCostUsd;
  return {
    downtimeAvoidedHours,
    truckRollsSavedAssumed,
    opexSavedUsdEstimate,
  };
}
