import { afterEach, describe, expect, it, vi } from "vitest";
import { api, validateSnapshot } from "./api";
import type { Snapshot } from "../types/api";

afterEach(() => vi.unstubAllGlobals());
function respond(body: unknown, status = 200) {
  const fetcher = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}
describe("typed API transport", () => {
  it("uses relative paths and encodes fault parameters", async () => {
    const fetcher = respond({ ok: true });
    await api.inject("SLY test&1", 3, "run-token");
    expect(fetcher.mock.calls[0][0]).toBe(
      "/api/control/inject?node_id=SLY+test%261&kind=3&run_id=run-token",
    );
    expect(fetcher.mock.calls[0][1].method).toBe("POST");
  });
  it("treats engine rejection in a 200 response as a failed command", async () => {
    respond({ ok: false, reason: "no crew available" });
    await expect(api.approve(5, "run-token")).rejects.toThrow(
      "no crew available",
    );
  });
  it("surfaces a failed Day 30 reset returned by manual step", async () => {
    respond({
      advanced: false,
      reset: false,
      error:
        "Demo restart failed. The completed world was preserved and paused.",
    });
    await expect(api.step("run-token")).rejects.toThrow(
      "Demo restart failed. The completed world was preserved and paused.",
    );
  });
  it("preserves useful validation errors", async () => {
    respond({ detail: "already faulty" }, 409);
    await expect(api.inject("site", 3, "run-token")).rejects.toThrow(
      "already faulty",
    );
  });
  it("requests a same-run telemetry window without absolute URLs", async () => {
    const fetcher = respond({
      run_id: "run / token",
      timeframe: "24h",
      tick_minutes: 5,
      samples: [],
    });
    await api.telemetryHistory("24h", "run / token");
    expect(fetcher.mock.calls[0][0]).toBe(
      "/api/telemetry/history?timeframe=24h&run_id=run+%2F+token",
    );
  });
  it("sends the server cursor unchanged", async () => {
    const fetcher = respond({
      tick: 42,
      run_id: "run-token",
      dashboard: {},
      control: {},
      nodes: [],
    });
    await api.delta(42);
    expect(fetcher.mock.calls[0][0]).toBe("/api/delta?since=42");
  });
  it("does not silently accept an outdated API", () => {
    expect(() =>
      validateSnapshot({ tick: 1, nodes: [] } as unknown as Snapshot),
    ).toThrow("Dashboard API mismatch");
  });
});
