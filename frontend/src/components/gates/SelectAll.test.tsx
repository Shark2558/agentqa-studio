import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SelectAll } from "./SelectAll";

const NOUN = ["defect", "defects"] as const;
const IDS = ["DEF-001", "DEF-002", "DEF-003"];

afterEach(cleanup);

describe("SelectAll", () => {
  it("names how many it selects, so a partial list is not read as all of them", () => {
    render(<SelectAll ids={IDS} selected={new Set()} noun={NOUN} onToggleAll={vi.fn()} />);
    expect(screen.getByRole("checkbox", { name: "Select the 3 defects shown" })).not.toBeChecked();
    cleanup();
    render(<SelectAll ids={["DEF-001"]} selected={new Set()} noun={NOUN} onToggleAll={vi.fn()} />);
    expect(screen.getByRole("checkbox", { name: "Select the 1 defect shown" })).toBeInTheDocument();
  });

  it("is ticked only when every item shown is selected, and part-ticked in between", () => {
    const { rerender } = render(<SelectAll ids={IDS} selected={new Set(["DEF-002"])} noun={NOUN} onToggleAll={vi.fn()} />);
    const box = screen.getByRole("checkbox", { name: "Select the 3 defects shown" }) as HTMLInputElement;
    expect(box).not.toBeChecked();
    expect(box.indeterminate).toBe(true);
    rerender(<SelectAll ids={IDS} selected={new Set([...IDS, "DEF-009"])} noun={NOUN} onToggleAll={vi.fn()} />);
    expect(box).toBeChecked();
    expect(box.indeterminate).toBe(false);
  });

  it("selects every item shown, or clears them", () => {
    const onToggleAll = vi.fn();
    const { rerender } = render(<SelectAll ids={IDS} selected={new Set(["DEF-002"])} noun={NOUN} onToggleAll={onToggleAll} />);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onToggleAll).toHaveBeenLastCalledWith(IDS, true);
    rerender(<SelectAll ids={IDS} selected={new Set(IDS)} noun={NOUN} onToggleAll={onToggleAll} />);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onToggleAll).toHaveBeenLastCalledWith(IDS, false);
  });

  it("shows nothing when nothing is listed", () => {
    render(<SelectAll ids={[]} selected={new Set()} noun={NOUN} onToggleAll={vi.fn()} />);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});
