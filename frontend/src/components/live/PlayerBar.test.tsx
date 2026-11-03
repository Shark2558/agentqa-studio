import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PlayerBar } from "./PlayerBar";

afterEach(cleanup);

describe("PlayerBar", () => {
  it("keeps the position counter out of the screen reader's live announcements, and names the state instead", () => {
    render(<PlayerBar player={{ pos: 3, playing: false, speed: 1, follow: false }} pos={3} total={10} ended={null} dispatch={vi.fn()} />);
    expect(screen.getByText("3 / 10").closest("[role=status]")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Paused");
    expect(screen.getByRole("slider", { name: "Position in the run" })).toHaveAttribute("aria-valuetext", "event 3 of 10");
  });

  it("says when it follows the run live and when it shows the final picture", () => {
    const { rerender } = render(<PlayerBar player={{ pos: 10, playing: true, speed: 1, follow: true }} pos={10} total={10} ended={null} dispatch={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Following the run live");
    rerender(<PlayerBar player={{ pos: 10, playing: false, speed: 2, follow: false }} pos={10} total={10} ended="finished" dispatch={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Final picture");
  });

  it.each([
    ["the Final picture button", { pos: 10, playing: true, speed: 2 as const, follow: true }],
    ["a replay that played to the end", { pos: 10, playing: true, speed: 2 as const, follow: false }],
  ])("at the end of a finished run after %s it says Final picture, and Play starts again from the beginning (Phase C)", (_how, player) => {
    const dispatch = vi.fn();
    render(<PlayerBar player={player} pos={10} total={10} ended="finished" dispatch={dispatch} />);
    expect(screen.getByRole("status")).toHaveTextContent("Final picture");
    expect(screen.getByText("10 / 10")).toBeInTheDocument();                       // no "· playing"
    const play = screen.getByRole("button", { name: "Play from the start" });
    expect(play).toBeEnabled();                                                      // never disabled under the reader's focus
    fireEvent.click(play);
    expect(dispatch).toHaveBeenCalledWith({ type: "restart" });
  });

  it("a recording that stopped without finishing, played to its end, says so and is not playing (Phase C review)", () => {
    render(<PlayerBar player={{ pos: 10, playing: true, speed: 2, follow: false }} pos={10} total={10} ended="idle" dispatch={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("End of what was recorded");
    expect(screen.getByText("10 / 10")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Play from the start" })).toBeEnabled();
  });

  it("a replay that caught up with a run still streaming keeps playing as new events arrive", () => {
    render(<PlayerBar player={{ pos: 10, playing: true, speed: 1, follow: false }} pos={10} total={10} ended={null} dispatch={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Playing");
    expect(screen.getByRole("button", { name: "Pause" })).toBeEnabled();
  });
});
