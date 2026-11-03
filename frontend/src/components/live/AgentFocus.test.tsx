import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Lane } from "../../lib/live/lanes";
import { demoLive, demoModel } from "../../test-fixtures/live";
import { AgentFocus, BrowserFrame } from "./AgentFocus";

const LANE: Lane = {
  key: "gw0", agent: "executor", url: "javascript:alert(1)", role: "admin", case: "TC-007", shot: "s-0001.jpg",
  box: { x: 100, y: 50, width: 200, height: 40, vw: 1280, vh: 720 }, caption: "click Save", kind: "action",
  steps: ["click Save", "fill Name"], verdict: { level: "bad", text: "expected 'Saved'" }, lastT: 1,
};

// The first recorded event with a screenshot: at that position its agent's frame shows that screen.
const SHOT_AT = demoLive.findIndex((e) => typeof e.shot === "string");
const focusAt = (pos: number, agent: string | null) => (
  <AgentFocus slug="demo" session="s1" model={demoModel(pos)} events={demoLive} pos={pos} agent={agent} runOver={false} />
);

afterEach(() => {
  cleanup();
  document.getElementById("root")?.remove();
});

describe("BrowserFrame", () => {
  it("shows the address as text, never a link, with the element being acted on outlined", () => {
    render(<BrowserFrame lane={LANE} running src={(s) => `/shots/${s}`} onOpen={vi.fn()} />);
    expect(screen.getByText("javascript:alert(1)").closest("a")).toBeNull();
    expect(document.querySelector("a")).toBeNull();
    const box = document.querySelector<HTMLElement>(".shotwrap .box");
    expect(box?.style.left).toBe(`${(100 / 1280) * 100}%`);
    expect(screen.getByText("expected 'Saved'")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Earlier steps" })).toHaveTextContent("fill Name");
  });
});

describe("the enlarged screenshot", () => {
  it("opens as a dialog over a page closed to the keyboard; Escape closes it and focus returns to the screen", () => {
    const root = document.body.appendChild(Object.assign(document.createElement("div"), { id: "root" }));
    render(focusAt(SHOT_AT + 1, demoLive[SHOT_AT].agent), { container: root });
    const open = screen.getByRole("button", { name: /^Enlarge the screen: / });
    fireEvent.click(open);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(root.contains(dialog)).toBe(false);
    expect(root).toHaveAttribute("inert");
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(root).not.toHaveAttribute("inert");
    expect(open).toHaveFocus();
  });

  it("keeps focus on Close while new events arrive behind it", () => {
    const agent = demoLive[SHOT_AT].agent;
    const { rerender } = render(focusAt(SHOT_AT + 1, agent));
    const open = screen.getByRole("button", { name: /^Enlarge the screen: / });
    const focused = vi.fn();
    open.addEventListener("focus", focused);
    fireEvent.click(open);
    rerender(focusAt(SHOT_AT + 1, agent));
    rerender(focusAt(SHOT_AT + 1, agent));
    expect(focused).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
  });
});

describe("the activity of the chosen agent", () => {
  it("follows the newest row while the reader is at the bottom, and stays put once they scroll up", () => {
    const { rerender } = render(focusAt(50, null));
    const log = screen.getByRole("log");
    Object.defineProperty(log, "scrollTop", { configurable: true, writable: true, value: 0 });
    Object.defineProperty(log, "clientHeight", { configurable: true, value: 300 });
    Object.defineProperty(log, "scrollHeight", { configurable: true, value: 5000 });
    rerender(focusAt(60, null));
    expect(log.scrollTop).toBe(5000);
    log.scrollTop = 100;
    fireEvent.scroll(log);
    Object.defineProperty(log, "scrollHeight", { configurable: true, value: 6000 });
    rerender(focusAt(70, null));
    expect(log.scrollTop).toBe(100);
  });
});
