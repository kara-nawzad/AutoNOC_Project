import { describe, expect, it } from "vitest";
import { estimateIllustrativeRoi, roiAssumptions } from "./roiEstimate";

describe("illustrative ROI scenario", () => {
  it("applies only the explicitly labeled user-provided assumptions", () => {
    const result = estimateIllustrativeRoi(10, 2);
    expect(result.downtimeAvoidedHours).toBe(
      10 * roiAssumptions.averageRepairHoursPerPreemption -
        2 * roiAssumptions.travelHoursPerFalseDispatch,
    );
    expect(result.truckRollsSavedAssumed).toBe(8);
    expect(result.opexSavedUsdEstimate).toBe(
      result.downtimeAvoidedHours *
        roiAssumptions.slaPenaltyUsdPerDowntimeHour +
        8 * roiAssumptions.truckRollCostUsd,
    );
  });

  it("does not credit a negative number of assumed avoided truck rolls", () => {
    const result = estimateIllustrativeRoi(1, 3);
    expect(result.truckRollsSavedAssumed).toBe(0);
    expect(result.downtimeAvoidedHours).toBe(4.2 - 1.5);
  });

  it("treats invalid counters as zero", () => {
    expect(
      estimateIllustrativeRoi(Number.NaN, Number.POSITIVE_INFINITY),
    ).toEqual({
      downtimeAvoidedHours: 0,
      truckRollsSavedAssumed: 0,
      opexSavedUsdEstimate: 0,
    });
  });
});
