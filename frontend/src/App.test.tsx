import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { PageFrame } from "./App";

function Broken(): never {
  throw new Error("Failed to fetch dynamically imported module");       // what a stale lazy chunk throws after an update
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PageFrame", () => {
  it("shows a message in place of a page that cannot load, instead of blanking the app", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});            // React reports the caught error; expected here
    render(<MemoryRouter><PageFrame><Broken /></PageFrame></MemoryRouter>);
    expect(screen.getByRole("alert")).toHaveTextContent("This page could not be loaded.");
  });
});
