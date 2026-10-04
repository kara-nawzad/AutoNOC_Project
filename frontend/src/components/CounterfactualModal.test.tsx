import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CounterfactualModal } from "./CounterfactualModal";
import type { Snapshot } from "../types/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("shows the paired study with non-currency units and closes accessibly", () => {
  Object.defineProperty(window.HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.open = true;
    },
  });
  Object.defineProperty(window.HTMLDialogElement.prototype, "close", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.open = false;
    },
  });
  const onClose = vi.fn();
  const data = {
    ai: {
      ai_enabled: false,
      pre_empted: 0,
      false_dispatches: 0,
    },
  } as unknown as Snapshot;

  render(<CounterfactualModal data={data} onClose={onClose} />);

  expect(
    screen.getByRole("heading", {
      name: "A1 Autonomous Intent — Economic & Operational Impact",
    }),
  ).toBeInTheDocument();
  expect(screen.getByText("19,418 units lower · 18.6%")).toBeInTheDocument();
  expect(screen.getByText("+8.6 h used · not saved")).toBeInTheDocument();
  expect(screen.getByText(/it is not USD/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Close impact report" }));
  expect(onClose).toHaveBeenCalledOnce();
});
