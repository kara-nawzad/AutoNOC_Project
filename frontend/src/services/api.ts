import type { ActionResult, Config, Snapshot } from "../types/api";

/** Relative paths deliberately use Vite's proxy / FastAPI's same origin. */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const timeout = AbortSignal.timeout(15_000);
  const signal = init.signal
    ? AbortSignal.any([init.signal, timeout])
    : timeout;
  const response = await fetch(path, { ...init, signal, cache: "no-store" });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  if (body === null)
    throw new Error("The server returned an invalid response.");
  return body as T;
}
export function validateSnapshot(value: Snapshot): Snapshot {
  // Fail visibly rather than silently rendering an old backend as zeroes.
  if (
    !value.dashboard ||
    !value.control ||
    !Array.isArray(value.nodes) ||
    !Number.isFinite(value.tick)
  ) {
    throw new Error(
      "Dashboard API mismatch. Restart the updated AutoNOC backend.",
    );
  }
  return value;
}
async function control(
  path: string,
  params: Record<string, string | number | boolean> = {},
): Promise<ActionResult> {
  const query = new URLSearchParams(
    Object.entries(params).map(([key, val]) => [key, String(val)]),
  );
  const result = await request<ActionResult>(`/api/control/${path}?${query}`, {
    method: "POST",
  });
  if (result.ok === false)
    throw new Error(result.reason || "The engine rejected this action.");
  return result;
}
export const api = {
  config: (signal?: AbortSignal) => request<Config>("/api/config", { signal }),
  delta: async (cursor: number, signal?: AbortSignal) =>
    validateSnapshot(
      await request<Snapshot>(`/api/delta?since=${cursor}`, { signal }),
    ),
  pause: () => control("pause"),
  resume: () => control("resume"),
  step: () => control("step"),
  speed: (value: number) => control("speed", { value }),
  cut: (ring: number) =>
    control("cut-fiber", {
      ring_id: ring,
      isolate: true,
      cause: "construction",
    }),
  inject: (node: string, kind: number) =>
    control("inject", { node_id: node, kind }),
  ai: (enabled: boolean, autoApprove = 0) =>
    control("ai", { enabled, auto_approve_seconds: autoApprove }),
  approve: (id: number) => control(`approve/${id}`),
  veto: (id: number) => control(`veto/${id}`),
};
