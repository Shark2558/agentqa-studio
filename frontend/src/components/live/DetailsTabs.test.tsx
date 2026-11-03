import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { demoLive, demoModel } from "../../test-fixtures/live";
import { DetailsTabs, type Tab } from "./DetailsTabs";

afterEach(cleanup);

const show = (tab: Tab) =>
  render(<DetailsTabs model={demoModel()} events={demoLive} pos={demoLive.length} tab={tab} onTab={vi.fn()} labels={(a) => a} />);

describe("DetailsTabs", () => {
  it("is a section under its own heading, and only the chosen tab points at a panel, which can take focus", () => {
    show("document");
    expect(screen.getByRole("heading", { name: "Details" })).toBeInTheDocument();
    const tabs = screen.getAllByRole("tab");
    expect(tabs.filter((t) => t.hasAttribute("aria-controls"))).toHaveLength(1);
    expect(screen.getByRole("tabpanel")).toHaveAttribute("tabindex", "0");
  });

  it("gives the site map a list of its screens, so a screen reader can reach every one", () => {
    show("map");
    expect(screen.getByRole("img", { name: /Site map: \d+ screens/ })).toBeInTheDocument();
    const list = screen.getByRole("table", { name: "Screens found" });
    expect(within(list).getByText("/help/faq")).toBeInTheDocument();
    expect(within(list).getByText("HTTP 404")).toBeInTheDocument();
  });

  it("lets a keyboard reach the map's scrolling area", () => {
    show("map");
    expect(screen.getByRole("region", { name: "Site map, scrolls sideways" })).toHaveAttribute("tabindex", "0");
  });

  it("the activity list reads only up to the replay position", () => {
    render(<DetailsTabs model={demoModel(5)} events={demoLive} pos={5} tab="activity" onTab={vi.fn()} labels={(a) => a} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
  });
});
