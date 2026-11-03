import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { demoModel } from "../../test-fixtures/live";
import { Findings, TestTiles } from "./TestsAndFindings";

afterEach(cleanup);

describe("TestTiles", () => {
  it("lists the tests that did not pass with their messages, for keyboard, touch and screen-reader users", () => {
    render(<TestTiles panels={demoModel().panels} runOver />);
    const list = screen.getByRole("list", { name: "Tests that did not pass" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(13);              // 10 failed + 3 not run
    expect(within(list).getAllByText(/failed/).length).toBeGreaterThanOrEqual(10);
  });
});

describe("Findings", () => {
  it("says how many findings it left out", () => {
    const panels = { ...demoModel().panels, hiddenFindings: 42 };
    render(<Findings panels={panels} />);
    expect(screen.getByText(/42 more not shown/)).toBeInTheDocument();
  });

  it("keeps a long list in a scrolling area a keyboard can reach", () => {
    render(<Findings panels={demoModel().panels} />);
    expect(screen.getByRole("list", { name: "Findings, worst first" })).toHaveAttribute("tabindex", "0");
  });
});
