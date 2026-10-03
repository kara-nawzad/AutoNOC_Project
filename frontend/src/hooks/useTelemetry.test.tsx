import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { useTelemetry } from "./useTelemetry";
import { api } from "../services/api";
vi.mock("../services/api", () => ({
  api: { config: vi.fn(), delta: vi.fn() },
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it("loads config once, follows server ticks, and aborts on unmount", async () => {
  vi.mocked(api.config).mockResolvedValue({
    presentation: { poll_ms: 10_000 },
  } as never);
  vi.mocked(api.delta).mockResolvedValue({ tick: 8, run_id: "run1" } as never);
  const { result, unmount } = renderHook(() => useTelemetry());
  await waitFor(() => expect(result.current.status).toBe("live"));
  expect(result.current.data?.tick).toBe(8);
  act(() => result.current.refresh());
  await waitFor(() => expect(api.delta).toHaveBeenCalledTimes(2));
  expect(api.config).toHaveBeenCalledTimes(1);
  expect(vi.mocked(api.delta).mock.calls[1][0]).toBe(8);
  const signal = vi.mocked(api.delta).mock.calls[1][1];
  unmount();
  expect(signal?.aborted).toBe(true);
});

it("keeps the last frame visible on a connection failure", async () => {
  vi.mocked(api.config).mockResolvedValue({
    presentation: { poll_ms: 10_000 },
  } as never);
  vi.mocked(api.delta)
    .mockResolvedValueOnce({ tick: 8, run_id: "run1" } as never)
    .mockRejectedValue(new Error("offline"));
  const { result } = renderHook(() => useTelemetry());
  await waitFor(() => expect(result.current.status).toBe("live"));
  act(() => result.current.refresh());
  await waitFor(() => expect(result.current.status).toBe("reconnecting"));
  expect(result.current.data?.tick).toBe(8);
  expect(result.current.error).toBe("offline");
});
