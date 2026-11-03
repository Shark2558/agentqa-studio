import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { STORAGE_KEY, resetThemeStoreForTests } from "../lib/theme";
import { ThemeMenu } from "./ThemeMenu";

beforeEach(() => resetThemeStoreForTests());

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
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
    expect(screen.getByText(/Colour: Teal/)).toBeVisible();          // the chosen accent is named, not colour alone
  });

  it("applies and saves a theme and an accent at once", () => {
    render(<ThemeMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Appearance" }));
    fireEvent.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    fireEvent.click(screen.getByRole("radio", { name: "Teal" }));
    expect(document.documentElement.getAttribute("data-accent")).toBe("teal");
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")).toEqual({ mode: "dark", accent: "teal" });
  });

  it("closes on Escape from anywhere (focus back on the button) and on a tap or click outside", () => {
    render(
      <div>
        <ThemeMenu />
        <p>elsewhere</p>
      </div>,
    );
    const button = screen.getByRole("button", { name: "Appearance" });
    fireEvent.click(button);
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(document.activeElement).toBe(button);
    fireEvent.click(button);
    fireEvent.pointerDown(screen.getByText("elsewhere"));
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("two menus on one page stay in step, and a choice survives a remount even when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const view = render(
      <>
        <ThemeMenu />
        <ThemeMenu placement="down" />
      </>,
    );
    const [first, second] = screen.getAllByRole("button", { name: "Appearance" });
    fireEvent.click(first);
    fireEvent.click(screen.getByRole("radio", { name: "Dark" }));
    fireEvent.click(second);
    expect(screen.getAllByRole("radio", { name: "Dark" }).every((r) => (r as HTMLInputElement).checked)).toBe(true);
    view.unmount();
    render(<ThemeMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Appearance" }));
    expect(screen.getByRole("radio", { name: "Dark" })).toBeChecked();   // the page keeps the choice it shows
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("follows a change made in another tab", () => {
    render(<ThemeMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Appearance" }));
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ mode: "light", accent: "green" }));
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: STORAGE_KEY }));
    });
    expect(screen.getByRole("radio", { name: "Green" })).toBeChecked();
    expect(document.documentElement.getAttribute("data-accent")).toBe("green");
  });
});
