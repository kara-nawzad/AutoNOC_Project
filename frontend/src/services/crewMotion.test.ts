import { describe, expect, it } from "vitest";
import { CrewMotion, type CrewFrame } from "./crewMotion";

function frame(
  tick: number,
  lon: number,
  paused = false,
  runId = "run-1",
): CrewFrame {
  return { tick, paused, runId, teams: [{ id: 1, lat: 35.56, lon }] };
}
function moving() {
  const motion = new CrewMotion(1000);
  motion.push(frame(0, 45.4), 0);
  motion.push(frame(1, 45.41), 1000);
  return motion;
}

describe("confirmed crew position interpolation", () => {
  it("moves at constant speed through the end of a poll, not an ease-out burst", () => {
    const motion = moving();
    const xs = [1100, 1300, 1500, 1700, 1900, 2100].map(
      (t) => motion.position(1, t)![1],
    );
    const step = xs[1] - xs[0];
    for (let i = 2; i < xs.length; i++)
      expect(xs[i] - xs[i - 1]).toBeCloseTo(step, 10);
    expect(step).toBeGreaterThan(0);
  });
  it("retargets without a position jump and ignores duplicate snapshots", () => {
    const motion = moving();
    const before = motion.position(1, 2000)!;
    motion.push(frame(2, 45.42), 2000);
    expect(motion.position(1, 2000)).toEqual(before);
    const at = motion.position(1, 2400);
    motion.push(frame(2, 45.42), 2400);
    expect(motion.position(1, 2400)).toEqual(at);
    expect(motion.position(1, 3200)![1]).toBeCloseTo(45.42);
  });
  it("spreads movement across slow ticks even when polls repeat the same tick", () => {
    const motion = new CrewMotion(1000);
    motion.push(frame(0, 45.4), 0);
    for (const t of [1000, 2000, 3000]) motion.push(frame(0, 45.4), t);
    motion.push(frame(1, 45.41), 4000);
    expect(motion.position(1, 5000)![1]).toBeCloseTo(45.4 + 0.01 / 4.8);
    expect(motion.position(1, 7900)![1]).toBeLessThan(45.41);
    expect(motion.position(1, 7900)![1]).toBeGreaterThan(
      motion.position(1, 7800)![1],
    );
  });
  it("settles briefly on pause, stays stopped, and interpolates a single step", () => {
    const motion = moving();
    const before = motion.position(1, 1300);
    motion.push(frame(1, 45.41, true), 1300);
    expect(motion.position(1, 1300)).toEqual(before);
    expect(motion.position(1, 1500)![1]).toBeCloseTo(45.41);
    expect(motion.position(1, 10000)).toEqual(motion.position(1, 1500));
    motion.push(frame(2, 45.42, true), 11000);
    expect(motion.position(1, 11100)![1]).toBeCloseTo(45.415);
    expect(motion.position(1, 11200)![1]).toBeCloseTo(45.42);
  });
  it("never extrapolates when updates stop; reduced motion and hiding settle", () => {
    const motion = moving();
    expect(motion.position(1, 100000)![1]).toBe(45.41);
    motion.push(frame(2, 45.42), 3000, true);
    expect(motion.position(1, 3000)![1]).toBe(45.42);
    motion.push(frame(3, 45.43), 4000);
    motion.settle();
    expect(motion.position(1, 4000)![1]).toBe(45.43);
  });
  it("resets for a new run and removes disappeared crews", () => {
    const motion = moving();
    motion.push(frame(0, 45.3, false, "run-2"), 1200);
    expect(motion.position(1, 1200)![1]).toBe(45.3);
    motion.push({ ...frame(1, 0, false, "run-2"), teams: [] }, 1500);
    expect(motion.position(1, 1600)).toBeUndefined();
  });
  it("gives identical positions at 30, 60, and 120 Hz", () => {
    const results = [30, 60, 120].map((hz) => {
      const motion = moving();
      for (let t = 1000; t < 1750; t += 1000 / hz) motion.position(1, t);
      return motion.position(1, 1750);
    });
    expect(results[0]).toEqual(results[1]);
    expect(results[1]).toEqual(results[2]);
  });
});
