import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ProgressBar } from "./ProgressBar";

afterEach(cleanup);

describe("ProgressBar", () => {
  it("exposes the value as a progress bar and clamps it to 0..1", () => {
    render(<ProgressBar value={0.38} label="Run progress" />);
    const bar = screen.getByRole("progressbar", { name: "Run progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "38");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    cleanup();
    render(<ProgressBar value={1.7} label="Upload" />);
    expect(screen.getByRole("progressbar", { name: "Upload" })).toHaveAttribute("aria-valuenow", "100");
    cleanup();
    render(<ProgressBar value={-2} label="Upload" />);
    expect(screen.getByRole("progressbar", { name: "Upload" })).toHaveAttribute("aria-valuenow", "0");
  });

  it("fills by a transform, never by width, so the motion stays on the compositor", () => {
    render(<ProgressBar value={0.5} label="Run progress" />);
    const fill = screen.getByRole("progressbar", { name: "Run progress" }).firstElementChild as HTMLElement;
    expect(fill.style.getPropertyValue("--p")).toBe("0.5");
    expect(fill.style.width).toBe("");
  });
});
