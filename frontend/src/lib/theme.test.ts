import { afterEach, describe, expect, it } from "vitest";
import bootScript from "../../public/theme-boot.js?raw";
import { ACCENTS, DEFAULT_PREFERENCE, MODES, STORAGE_KEY, applyPreference, loadPreference, parsePreference, savePreference } from "./theme";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-accent");
});

describe("parsePreference", () => {
  it("falls back to system + blue for nothing, bad JSON, unknown values and prototype keys", () => {
    expect(parsePreference(null)).toEqual(DEFAULT_PREFERENCE);
    expect(parsePreference("{not json")).toEqual(DEFAULT_PREFERENCE);
    expect(parsePreference(JSON.stringify({ mode: "neon", accent: "pink" }))).toEqual(DEFAULT_PREFERENCE);
    expect(parsePreference(JSON.stringify({ mode: "__proto__", accent: "constructor" }))).toEqual(DEFAULT_PREFERENCE);
    expect(parsePreference(JSON.stringify({ mode: "dark" }))).toEqual({ mode: "dark", accent: "blue" });
  });

  it("round-trips a saved choice", () => {
    savePreference({ mode: "dark", accent: "teal" });
    expect(loadPreference()).toEqual({ mode: "dark", accent: "teal" });
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toEqual({ mode: "dark", accent: "teal" });
  });

  it("survives a storage that throws (private windows)", () => {
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    } as unknown as Storage;
    expect(loadPreference(broken)).toEqual(DEFAULT_PREFERENCE);
    expect(() => savePreference({ mode: "light", accent: "green" }, broken)).not.toThrow();
  });
});

describe("applyPreference", () => {
  it("sets both attributes on <html>, and removes data-theme for system so the OS decides", () => {
    applyPreference({ mode: "dark", accent: "slate" });
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(document.documentElement.getAttribute("data-accent")).toBe("slate");
    applyPreference({ mode: "system", accent: "blue" });
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(document.documentElement.getAttribute("data-accent")).toBe("blue");
  });
});

describe("theme-boot.js", () => {
  it("knows the same storage key, modes and accents as the app (no drift)", () => {
    expect(bootScript).toContain(STORAGE_KEY);
    for (const mode of MODES) expect(bootScript).toContain(`"${mode}"`);
    for (const accent of ACCENTS) expect(bootScript).toContain(`"${accent.id}"`);
    expect(bootScript).not.toMatch(/\b(const|let|=>)\b/);          // plain ES5: runs before anything else, on any browser
  });
});
