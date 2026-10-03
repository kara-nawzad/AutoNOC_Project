import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import type { Config, Snapshot } from "../types/api";

/** One cancellable request at a time. Controls can request an immediate refresh
 * without racing older polls. History and simulation time always come from Python. */
export function useTelemetry() {
  const [config, setConfig] = useState<Config | null>(null);
  const [data, setData] = useState<Snapshot | null>(null);
  const [status, setStatus] = useState<"connecting" | "live" | "reconnecting">(
    "connecting",
  );
  const [error, setError] = useState<string | null>(null);
  const refreshRef = useRef<() => void>(() => undefined);
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let busy = false,
      again = false,
      cursor = 0,
      cfg: Config | null = null,
      runId = "";
    async function poll() {
      if (abort.signal.aborted) return;
      if (busy) {
        again = true;
        return;
      }
      clearTimeout(timer);
      busy = true;
      try {
        if (!cfg) {
          cfg = await api.config(abort.signal);
          if (!cfg.presentation)
            throw new Error(
              "Updated presentation API not found. Restart the backend.",
            );
          setConfig(cfg);
        }
        const next = await api.delta(cursor, abort.signal);
        if (abort.signal.aborted) return;
        // Complete bounded readouts replace rather than merge stale entities.
        if (runId !== next.run_id) runId = next.run_id;
        cursor = next.tick;
        setData(next);
        setStatus("live");
        setError(null);
      } catch (err) {
        if (!abort.signal.aborted) {
          setStatus("reconnecting");
          setError(err instanceof Error ? err.message : "Connection lost");
        }
      } finally {
        busy = false;
        if (!abort.signal.aborted) {
          timer = setTimeout(
            poll,
            again ? 0 : (cfg?.presentation.poll_ms ?? 1000),
          );
          again = false;
        }
      }
    }
    refreshRef.current = () => {
      void poll();
    };
    void poll();
    return () => {
      abort.abort();
      clearTimeout(timer);
      refreshRef.current = () => undefined;
    };
  }, []);
  return {
    config,
    data,
    status,
    error,
    refresh: useCallback(() => refreshRef.current(), []),
  };
}
