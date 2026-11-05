import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";
import { renderPage } from "../test-fixtures/gates";
import { Shell } from "./Shell";

vi.mock("./assist/NeedsYouDock", () => ({
  NeedsYouDock: () => {
    throw new Error("The help box broke");
  },
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the app frame", () => {
  it("keeps the page when the help box breaks: the box says so in its place and everything else stays", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderPage(<Shell><h1>The project</h1></Shell>, "/projects/demo", "/projects/:slug", {});
    expect(await screen.findByRole("heading", { name: "The project" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/help box could not be shown/i);
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });
});
