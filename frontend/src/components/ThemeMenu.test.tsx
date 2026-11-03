import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { STORAGE_KEY } from "../lib/theme";
import { ThemeMenu } from "./ThemeMenu";

afterEach(() => {
  cleanup();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-accent");
});

describe("ThemeMenu", () => {
  it("is a closed Appearance button until pressed, then shows the current choices", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ mode: "dark", accent: "teal" }));
    render(<ThemeMenu />);
    const button = screen.getByRole("button", { name: "Appearance" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("radio", { name: "Dark" })).toBeNull();
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("radio", { name: "Dark" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Teal" })).toBeChecked();
  });

  it("applies and saves a theme and an accent at once", () => {
    render(<ThemeMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Appearance" }));
    fireEvent.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    fireEvent.click(screen.getByRole("radio", { name: "Teal" }));
    expect(document.documentElement.getAttribute("data-accent")).toBe("teal");
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toEqual({ mode: "dark", accent: "teal" });
  });

  it("closes on Escape and returns focus to the button; closes on a click outside", () => {
    render(
      <div>
        <ThemeMenu />
        <p>elsewhere</p>
      </div>,
    );
    const button = screen.getByRole("button", { name: "Appearance" });
    fireEvent.click(button);
    fireEvent.keyDown(screen.getByRole("radio", { name: "Light" }), { key: "Escape" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(document.activeElement).toBe(button);
    fireEvent.click(button);
    fireEvent.mouseDown(screen.getByText("elsewhere"));
    expect(button).toHaveAttribute("aria-expanded", "false");
  });
});
