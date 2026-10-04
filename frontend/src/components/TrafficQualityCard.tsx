import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { PointerEvent } from "react";
import { motion } from "framer-motion";
import type {
  Config,
  Snapshot,
  TelemetrySample,
  TelemetryTimeframe,
} from "../types/api";
import { api } from "../services/api";
import { NumberTween } from "./NumberTween";
import { chartPath, Dot, PanelHeading } from "./ui";

const TIMEFRAMES: TelemetryTimeframe[] = ["30m", "24h", "7d"];
const WINDOW_MINUTES: Record<TelemetryTimeframe, number> = {
  "30m": 30,
  "24h": 24 * 60,
  "7d": 7 * 24 * 60,
};
const GRAPH_WIDTH = 320;
const GRAPH_HEIGHT = 100;

type Metric = "throughput_gbps" | "prb";

function mergeSamples(
  sources: TelemetrySample[][],
  firstTick: number,
  lastTick: number,
) {
  const byTick = new Map<number, TelemetrySample>();
  for (const source of sources) {
    for (const sample of source) {
      if (sample.tick >= firstTick && sample.tick <= lastTick)
        byTick.set(sample.tick, sample);
    }
  }
  return [...byTick.values()].sort((a, b) => a.tick - b.tick);
}

function coordinateY(value: number, domain: [number, number]) {
  const [low, high] = domain;
  const ratio = Math.max(
    0,
    Math.min(1, (value - low) / Math.max(high - low, 0.001)),
  );
  return GRAPH_HEIGHT - 3 - ratio * (GRAPH_HEIGHT - 6);
}

export function TrafficQualityCard({
  data,
  config,
}: {
  data: Snapshot;
  config: Config;
}) {
  const [timeframe, setTimeframe] = useState<TelemetryTimeframe>("30m");
  const [metric, setMetric] = useState<Metric>("throughput_gbps");
  const [longHistory, setLongHistory] = useState<TelemetrySample[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [hoveredTick, setHoveredTick] = useState<number | null>(null);
  const requestId = useRef(0);
  const id = useId().replace(/:/g, "");

  useEffect(() => {
    const request = ++requestId.current;
    if (timeframe === "30m") {
      setHistoryError(null);
      return () => {
        requestId.current += 1;
      };
    }
    setHistoryError(null);
    setLongHistory([]);
    void api
      .telemetryHistory(timeframe, data.run_id)
      .then((result) => {
        if (request !== requestId.current || result.run_id !== data.run_id)
          return;
        setLongHistory(result.samples);
      })
      .catch((error: unknown) => {
        if (request !== requestId.current) return;
        setHistoryError(
          error instanceof Error
            ? error.message
            : "Could not load this telemetry window.",
        );
      });
    return () => {
      requestId.current += 1;
    };
  }, [timeframe, data.run_id]);

  const sampleLimitTicks = Math.floor(
    WINDOW_MINUTES[timeframe] / config.tick_minutes,
  );
  const firstTick = Math.max(0, data.tick - sampleLimitTicks);
  const samples = useMemo(() => {
    const sources =
      timeframe === "30m"
        ? [data.dashboard.history]
        : [longHistory, data.dashboard.history];
    return mergeSamples(sources, firstTick, data.tick);
  }, [data.dashboard.history, data.tick, firstTick, longHistory, timeframe]);

  const current = data.dashboard.current;
  const activeSample =
    (hoveredTick === null
      ? undefined
      : samples.find((sample) => sample.tick === hoveredTick)) ?? current;
  const values = samples.map((sample) => sample[metric]);
  const drops = samples.map((sample) => sample.drop_rate);
  const trafficDomain: [number, number] =
    metric === "prb"
      ? [config.gauges.prb.lo, config.gauges.prb.hi]
      : [Math.min(...values), Math.max(...values)];
  const dropDomain: [number, number] = [0, Math.max(1, ...drops)];
  const traffic = chartPath(values, GRAPH_WIDTH, GRAPH_HEIGHT, trafficDomain);
  const dropPath = chartPath(drops, GRAPH_WIDTH, GRAPH_HEIGHT, dropDomain);
  const hoveredIndex =
    hoveredTick === null
      ? -1
      : samples.findIndex((sample) => sample.tick === hoveredTick);
  const crosshairX =
    samples.length <= 1
      ? GRAPH_WIDTH
      : (hoveredIndex / (samples.length - 1)) * GRAPH_WIDTH;
  const metricValue = activeSample[metric];
  const coverageMinutes =
    samples.length > 1
      ? (samples.at(-1)!.tick - samples[0].tick) * config.tick_minutes
      : 0;
  const requestedMinutes = WINDOW_MINUTES[timeframe];
  const tooltipLeft =
    hoveredIndex < 3
      ? "4%"
      : hoveredIndex > samples.length - 4
        ? "82%"
        : `${(hoveredIndex / Math.max(1, samples.length - 1)) * 100}%`;
  const primaryLabel = metric === "prb" ? "PRB utilization" : "QCI 9 traffic";

  function inspect(event: PointerEvent<SVGSVGElement>) {
    if (samples.length < 2) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const ratio = Math.max(
      0,
      Math.min(1, (event.clientX - bounds.left) / Math.max(bounds.width, 1)),
    );
    const index = Math.round(ratio * (samples.length - 1));
    setHoveredTick(samples[index].tick);
  }

  return (
    <article className="glass analytics-card traffic-card">
      <PanelHeading
        title="Traffic & quality"
        right={
          <div
            className="timeframe-tabs"
            role="group"
            aria-label="Telemetry timeframe"
          >
            {TIMEFRAMES.map((option) => (
              <button
                key={option}
                type="button"
                className={timeframe === option ? "selected" : ""}
                aria-pressed={timeframe === option}
                onClick={() => {
                  setTimeframe(option);
                  setHoveredTick(null);
                }}
              >
                {option}
              </button>
            ))}
          </div>
        }
      />
      <div className="chart-summary">
        <div>
          <NumberTween
            value={metricValue}
            decimals={metric === "prb" ? 1 : 2}
          />
          <span>{metric === "prb" ? "% PRB" : "Gbps"}</span>
        </div>
        <div
          className="segmented"
          role="group"
          aria-label="Primary chart metric"
        >
          <button
            type="button"
            className={metric === "throughput_gbps" ? "selected" : ""}
            aria-pressed={metric === "throughput_gbps"}
            onClick={() => {
              setMetric("throughput_gbps");
              setHoveredTick(null);
            }}
          >
            Traffic
          </button>
          <button
            type="button"
            className={metric === "prb" ? "selected" : ""}
            aria-pressed={metric === "prb"}
            onClick={() => {
              setMetric("prb");
              setHoveredTick(null);
            }}
          >
            PRB
          </button>
        </div>
      </div>
      <div className="chart-legend">
        <span>
          <Dot color={config.presentation.palette.fiber} />
          {primaryLabel}
        </span>
        <span title="Simulator aggregate packet-loss proxy, not a bearer-level measurement">
          <Dot color={config.presentation.palette.prediction} /> E-RAB drop
          proxy · independent scale
        </span>
      </div>
      <div className="chart-scale-labels">
        <span>
          {metric === "prb" ? "PRB" : "QCI 9"} ·{" "}
          {Math.min(...values).toFixed(metric === "prb" ? 1 : 2)}–
          {Math.max(...values).toFixed(metric === "prb" ? 1 : 2)}
          {metric === "prb" ? "%" : " Gbps"}
        </span>
        <span>
          E-RAB drop proxy · {Math.min(...drops).toFixed(3)}–
          {Math.max(...drops).toFixed(3)}%
        </span>
      </div>
      <div className="traffic-chart-wrap">
        <svg
          className="traffic-chart"
          viewBox={`0 0 ${GRAPH_WIDTH} 108`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`${timeframe} simulated ${primaryLabel} and E-RAB drop proxy history. Hover to inspect a sample.`}
          onPointerMove={inspect}
          onPointerLeave={() => setHoveredTick(null)}
        >
          <defs>
            <linearGradient id={`${id}-area`} x1="0" y1="0" x2="0" y2="1">
              <stop
                stopColor={config.presentation.palette.fiber}
                stopOpacity=".24"
              />
              <stop
                offset="1"
                stopColor={config.presentation.palette.fiber}
                stopOpacity="0"
              />
            </linearGradient>
          </defs>
          {[15, 45, 75, 105].map((y) => (
            <line
              key={y}
              x1="0"
              x2={GRAPH_WIDTH}
              y1={y}
              y2={y}
              stroke="rgba(255,255,255,.05)"
              strokeDasharray="3 5"
            />
          ))}
          {samples.length > 1 && (
            <motion.path
              d={`${traffic} L${GRAPH_WIDTH},105 L0,105 Z`}
              initial={false}
              animate={{ d: `${traffic} L${GRAPH_WIDTH},105 L0,105 Z` }}
              fill={`url(#${id}-area)`}
              transition={{ duration: 0.5 }}
            />
          )}
          <motion.path
            d={traffic}
            initial={false}
            animate={{ d: traffic }}
            fill="none"
            stroke={config.presentation.palette.fiber}
            strokeWidth="1.8"
            transition={{ duration: 0.5 }}
            vectorEffect="non-scaling-stroke"
          />
          <motion.path
            d={dropPath}
            initial={false}
            animate={{ d: dropPath }}
            fill="none"
            stroke={config.presentation.palette.prediction}
            strokeWidth="1.5"
            strokeDasharray="4 3"
            transition={{ duration: 0.5 }}
            vectorEffect="non-scaling-stroke"
          />
          {hoveredIndex >= 0 && (
            <>
              <line
                x1={crosshairX}
                x2={crosshairX}
                y1="8"
                y2="101"
                stroke="rgba(215,231,249,.6)"
                strokeDasharray="3 3"
              />
              <circle
                cx={crosshairX}
                cy={coordinateY(values[hoveredIndex], trafficDomain)}
                r="3.2"
                fill={config.presentation.palette.fiber}
                stroke="#07101a"
                strokeWidth="1.5"
              />
              <circle
                cx={crosshairX}
                cy={coordinateY(drops[hoveredIndex], dropDomain)}
                r="3.2"
                fill={config.presentation.palette.prediction}
                stroke="#07101a"
                strokeWidth="1.5"
              />
            </>
          )}
        </svg>
        {hoveredIndex >= 0 && (
          <div
            className="chart-tooltip"
            style={{ left: tooltipLeft }}
            role="tooltip"
          >
            <strong className="mono">{samples[hoveredIndex].sim_time}</strong>
            <span>
              {primaryLabel}:{" "}
              {values[hoveredIndex].toFixed(metric === "prb" ? 1 : 2)}
              {metric === "prb" ? "%" : " Gbps"}
            </span>
            <span>E-RAB drop proxy: {drops[hoveredIndex].toFixed(3)}%</span>
          </div>
        )}
      </div>
      <div className="chart-axis mono">
        <span>{samples[0]?.sim_time ?? "—"}</span>
        <span>
          {samples.length} SAMPLES · {coverageMinutes}/{requestedMinutes} SIM
          MIN
          {historyError ? " · HISTORY ERROR" : ""}
        </span>
        <span>{samples.at(-1)?.sim_time ?? current.sim_time}</span>
      </div>
      <p className="chart-provenance">
        {historyError
          ? historyError
          : timeframe === "30m"
            ? "Actual server samples · 5-minute simulation ticks"
            : "Actual current-run samples · longer windows fill as simulation time advances"}
      </p>
    </article>
  );
}
