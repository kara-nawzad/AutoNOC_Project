import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { HistoryModal } from "./HistoryModal";
import { api } from "../services/api";
import type { Config, RunSummary, Snapshot } from "../types/api";

vi.mock("../services/api", () => ({
  api: { history: vi.fn() },
}));

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it("labels completed summaries by completion date and simulated day, never run number", async () => {
  const showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true;
  });
  const close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false;
  });
  vi.stubGlobal("HTMLDialogElement", window.HTMLDialogElement);
  window.HTMLDialogElement.prototype.showModal = showModal;
  window.HTMLDialogElement.prototype.close = close;

  const completedAt = "2026-10-04T08:15:00Z";
  const summary: RunSummary = {
    completed_at: completedAt,
    simulated_days: 30,
    completed_sim_time: "D30 23:55",
    seed: 42,
    availability: 98.25,
    injected: 23,
    masked: 4,
    repairs: 21,
    mttr_min: 45.5,
    ats_failures: 1,
    fuel_thefts: 2,
    active_incidents: 3,
    ai_enabled: true,
    ai_mode: "ml",
    pre_empted: 6,
    acted_upon: 8,
    false_dispatches: 1,
    crew_hours_saved: 5.2,
    precision: 0.86,
  };
  vi.mocked(api.history).mockResolvedValue({ summaries: [summary] });
  const data = { run_id: "internal-run-id", logs: [] } as unknown as Snapshot;
  const config = { presentation: { severity_colors: {} } } as Config;
  render(<HistoryModal data={data} config={config} onClose={vi.fn()} />);

  fireEvent.click(screen.getByRole("tab", { name: "Completed demos" }));
  const time = await screen.findByText(/2026|Oct|October/);
  expect(time).toHaveAttribute("datetime", completedAt);
  expect(screen.getByText("30 simulated days")).toBeInTheDocument();
  expect(screen.getByText("Day 30 · D30 23:55")).toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(/Cycle\s+\d+/i);
});
