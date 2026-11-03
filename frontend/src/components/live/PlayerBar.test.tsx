import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { PlayerBar } from "./PlayerBar";

afterEach(cleanup);

describe("PlayerBar", () => {
  it("keeps the position counter out of the screen reader's live announcements, and names the state instead", () => {
    render(<PlayerBar player={{ pos: 3, playing: false, speed: 1, follow: false }} pos={3} total={10} runOver={false} dispatch={vi.fn()} />);
    expect(screen.getByText("3 / 10").closest("[role=status]")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Paused");
    expect(screen.getByRole("slider", { name: "Position in the run" })).toHaveAttribute("aria-valuetext", "event 3 of 10");
  });

  it("says when it follows the run live and when it shows the final picture", () => {
    const { rerender } = render(<PlayerBar player={{ pos: 10, playing: true, speed: 1, follow: true }} pos={10} total={10} runOver={false} dispatch={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Following the run live");
    rerender(<PlayerBar player={{ pos: 10, playing: false, speed: 2, follow: false }} pos={10} total={10} runOver dispatch={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Final picture");
  });
});
