import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { chartPath, Badge } from "./ui";
import { NumberTween } from "./NumberTween";
import type { Config } from "../types/api";

describe("presentation primitives", () => {
  it("handles empty and constant chart series without invalid SVG", () => {
    expect(chartPath([], 100, 30)).toBe("");
    for (const values of [[2], [2, 2, 2], [1, 9, 3]]) {
      const path = chartPath(values, 100, 30);
      expect(path).toMatch(/^M/);
      expect(path).not.toMatch(/NaN|Infinity|undefined/);
    }
  });
  it("uses the configured severity color, not a local mapping", () => {
    const cfg = {
      presentation: { severity_colors: { CRITICAL: "#123456" } },
    } as Config;
    render(<Badge config={cfg} severity="CRITICAL" />);
    expect(screen.getByText("CRITICAL")).toHaveStyle("--tone: #123456");
  });
  it("renders accessible precision before animation begins", () => {
    const { unmount } = render(
      <NumberTween value={98.24} decimals={2} suffix="%" />,
    );
    expect(screen.getByLabelText("98.24%")).toBeInTheDocument();
    expect(screen.getByText("98.24%")).toBeInTheDocument();
    unmount();
  });
});
