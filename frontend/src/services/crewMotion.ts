import type { LatLng, Team } from "../types/api";

type Position = Pick<Team, "id" | "lat" | "lon">;
export interface CrewFrame {
  runId: string;
  tick: number;
  paused: boolean;
  teams: Position[];
}
interface Track {
  from: LatLng;
  to: LatLng;
  started: number;
  duration: number;
}

/** Presentation-only interpolation of confirmed coordinates. No prediction,
 * route planning, simulation time or movement beyond the latest server point.
 * Linear travel covers a whole observed update interval (+20% jitter cushion),
 * instead of exponential easing that rushes forward then stalls every poll.
 * The visual fleet trails telemetry slightly; operational counters do not. */
export class CrewMotion {
  private tracks = new Map<number, Track>();
  private runId: string | null = null;
  private tick = -1;
  private advancedAt = 0;
  private cadence: number;
  private paused = false;

  constructor(private readonly pollMs: number) {
    this.cadence = pollMs;
  }

  position(id: number, now: number): LatLng | undefined {
    const track = this.tracks.get(id);
    if (!track) return undefined;
    const t =
      track.duration === 0
        ? 1
        : Math.max(0, Math.min(1, (now - track.started) / track.duration));
    return [
      track.from[0] + (track.to[0] - track.from[0]) * t,
      track.from[1] + (track.to[1] - track.from[1]) * t,
    ];
  }

  push(frame: CrewFrame, now: number, instant = false) {
    const reset = this.runId !== frame.runId || frame.tick < this.tick;
    const stopping = frame.paused && !this.paused;
    if (reset) {
      this.tracks.clear();
      this.cadence = this.pollMs;
      this.advancedAt = now;
    } else if (frame.paused || this.paused) {
      // Time spent paused must not inflate the next travel animation.
      this.advancedAt = now;
      this.cadence = this.pollMs;
    } else if (frame.tick > this.tick) {
      // Ignore duplicate polls/control refreshes. At slow simulator speeds a
      // server tick may span several polls; measure those actual observations.
      this.cadence = Math.min(
        8000,
        Math.max(this.pollMs, now - this.advancedAt),
      );
      this.advancedAt = now;
    }
    const duration =
      instant || reset ? 0 : frame.paused ? 200 : this.cadence * 1.2;
    const ids = new Set<number>();
    for (const team of frame.teams) {
      ids.add(team.id);
      const old = this.tracks.get(team.id);
      const to: LatLng = [team.lat, team.lon];
      // A duplicate endpoint must not restart or stretch the active segment.
      if (
        old &&
        !instant &&
        !stopping &&
        old.to[0] === to[0] &&
        old.to[1] === to[1]
      )
        continue;
      this.tracks.set(team.id, {
        from: this.position(team.id, now) ?? to,
        to,
        started: now,
        duration: old ? duration : 0,
      });
    }
    for (const id of this.tracks.keys())
      if (!ids.has(id)) this.tracks.delete(id);
    this.runId = frame.runId;
    this.tick = frame.tick;
    this.paused = frame.paused;
  }

  /** Hidden tabs/reduced-motion displays settle to confirmed positions, not
   * a long catch-up journey when the browser starts painting again. */
  settle() {
    for (const track of this.tracks.values()) {
      track.from = track.to;
      track.duration = 0;
    }
  }
}
