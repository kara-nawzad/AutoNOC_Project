/**
 * Checked-in M7 counterfactual report summary.
 * Source: reports/counterfactual_summary.json (30 matched seeds x 10 simulated days).
 * Keep these values in sync when that committed report is regenerated.
 */
export const counterfactualStudy = {
  seeds: 30,
  simulatedDaysPerSeed: 10,
  clairvoyantDowntimeHeadroomCapturedPct: 61.7,
  arms: {
    A: {
      label: "No AI · reactive dispatch",
      availabilityPct: 98.75,
      availabilityCi95: 0.02,
      downtimeTowerMinutes: 54_033,
      preemptedEpisodes: 0,
      falseDispatches: 0,
      crewHours: 773.33,
      crewHoursCi95: 13.48,
      costTowerMinutes: 104_229,
      costCi95: 1_200.72,
    },
    B: {
      label: "Advisory · human approval",
      availabilityPct: 98.75,
      downtimeTowerMinutes: 54_070,
      preemptedEpisodes: 0,
      falseDispatches: 4.37,
      crewHours: 778.9,
      costTowerMinutes: 104_384.83,
    },
    C: {
      label: "Autonomous · AutoNOC Commander",
      availabilityPct: 98.88,
      availabilityCi95: 0.02,
      downtimeTowerMinutes: 48_369,
      preemptedEpisodes: 448.03,
      falseDispatches: 3.77,
      crewHours: 781.89,
      crewHoursCi95: 13.71,
      costTowerMinutes: 84_811.33,
      costCi95: 1_006.49,
    },
    D: {
      label: "Clairvoyant · predictive upper bound",
      availabilityPct: 98.96,
      downtimeTowerMinutes: 44_856.5,
      preemptedEpisodes: 490.63,
      falseDispatches: 0.03,
      crewHours: 813.4,
      costTowerMinutes: 83_120.67,
    },
  },
} as const;

export const counterfactualDeltas = {
  availabilityPercentagePoints:
    counterfactualStudy.arms.C.availabilityPct -
    counterfactualStudy.arms.A.availabilityPct,
  downtimeTowerMinutes:
    counterfactualStudy.arms.A.downtimeTowerMinutes -
    counterfactualStudy.arms.C.downtimeTowerMinutes,
  crewHours:
    counterfactualStudy.arms.C.crewHours - counterfactualStudy.arms.A.crewHours,
  costTowerMinutes:
    counterfactualStudy.arms.A.costTowerMinutes -
    counterfactualStudy.arms.C.costTowerMinutes,
} as const;
