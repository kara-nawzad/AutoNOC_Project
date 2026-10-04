import { useEffect, useState } from "react";
import { CalendarClock, CircleCheck, Loader2 } from "lucide-react";
import type { Config, RunSummary, Snapshot } from "../types/api";
import { api } from "../services/api";
import { Badge, Modal } from "./ui";

function completionLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function SummaryCard({ summary }: { summary: RunSummary }) {
  return (
    <article className="run-summary-card">
      <div className="run-summary-heading">
        <div>
          <span className="run-summary-eyebrow">COMPLETED</span>
          <time dateTime={summary.completed_at}>
            {completionLabel(summary.completed_at)}
          </time>
        </div>
        <span className="run-summary-duration">
          {summary.simulated_days} simulated days
        </span>
      </div>
      <div className="run-summary-day">
        Day {summary.simulated_days} · {summary.completed_sim_time}
      </div>
      <div className="run-summary-grid">
        <div>
          <span>Availability</span>
          <strong>{summary.availability.toFixed(2)}%</strong>
        </div>
        <div>
          <span>Faults injected</span>
          <strong>{summary.injected.toLocaleString()}</strong>
        </div>
        <div>
          <span>Repairs</span>
          <strong>{summary.repairs.toLocaleString()}</strong>
        </div>
        <div>
          <span>Mean repair time</span>
          <strong>{summary.mttr_min.toFixed(1)} min</strong>
        </div>
        <div>
          <span>Power incidents</span>
          <strong>
            {(summary.ats_failures + summary.fuel_thefts).toLocaleString()}
          </strong>
        </div>
        <div>
          <span>AI actions</span>
          <strong>{summary.acted_upon.toLocaleString()}</strong>
        </div>
      </div>
      <p className="run-summary-foot">
        {summary.ai_enabled
          ? `${summary.ai_mode.toUpperCase()} · ${summary.pre_empted} pre-emptions`
          : "AI disabled"}
        {summary.precision !== null
          ? ` · ${Math.round(summary.precision * 100)}% measured precision`
          : ""}
      </p>
    </article>
  );
}

export function HistoryModal({
  data,
  config,
  onClose,
}: {
  data: Snapshot;
  config: Config;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"events" | "runs">("events");
  const [summaries, setSummaries] = useState<RunSummary[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    void api
      .history()
      .then((response) => {
        if (current) setSummaries(response.summaries);
      })
      .catch((error: unknown) => {
        if (current)
          setHistoryError(
            error instanceof Error
              ? error.message
              : "Run history is unavailable.",
          );
      });
    return () => {
      current = false;
    };
  }, []);

  return (
    <Modal title="History" onClose={onClose} wide>
      <div className="history-tabs" role="tablist" aria-label="History type">
        <button
          role="tab"
          aria-selected={tab === "events"}
          className={tab === "events" ? "selected" : ""}
          onClick={() => setTab("events")}
        >
          Network events
        </button>
        <button
          role="tab"
          aria-selected={tab === "runs"}
          className={tab === "runs" ? "selected" : ""}
          onClick={() => setTab("runs")}
        >
          Completed demos
        </button>
      </div>
      {tab === "events" ? (
        <>
          <p className="dialog-intro">
            Latest {data.logs.length} retained events · engine time. Cleared
            alarms remain here for context.
          </p>
          <div className="event-history">
            {[...data.logs].reverse().map((entry, i) => (
              <div
                className="history-row"
                key={`${data.run_id}-${entry.tick}-${i}-${entry.message}`}
              >
                <span className="mono">{entry.time}</span>
                <Badge config={config} severity={entry.severity} />
                <p>{entry.message}</p>
              </div>
            ))}
            {!data.logs.length && (
              <div className="empty-state">
                <CircleCheck size={24} />
                <strong>No events yet</strong>
                <span>Engine events will appear here.</span>
              </div>
            )}
          </div>
        </>
      ) : (
        <section className="run-history" aria-label="Completed demo summaries">
          <p className="dialog-intro">
            Recent 30-day summaries, retained across deployments. Completion
            times use your browser’s local timezone.
          </p>
          {historyError && (
            <div className="history-error" role="alert">
              {historyError}
            </div>
          )}
          {summaries === null && !historyError && (
            <div className="history-loading" role="status">
              <Loader2 className="spin" size={17} /> Loading summaries…
            </div>
          )}
          {summaries?.length ? (
            summaries.map((summary) => (
              <SummaryCard key={summary.completed_at} summary={summary} />
            ))
          ) : summaries && !historyError ? (
            <div className="empty-state">
              <CalendarClock size={24} />
              <strong>No completed demos yet</strong>
              <span>A summary will appear here after Day 30.</span>
            </div>
          ) : null}
        </section>
      )}
    </Modal>
  );
}
