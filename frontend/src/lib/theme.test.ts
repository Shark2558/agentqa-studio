import { afterEach, describe, expect, it } from "vitest";
import bootScript from "../../public/theme-boot.js?raw";
import { ACCENTS, DEFAULT_PREFERENCE, MODES, STORAGE_KEY, applyPreference, loadPreference, parsePreference, savePreference } from "./theme";

const root = () => document.documentElement;

afterEach(() => {
  localStorage.clear();
  root().removeAttribute("data-theme");
  root().removeAttribute("data-accent");
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
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")).toEqual({ mode: "dark", accent: "teal" });
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

  it("never hands out a shared mutable default", () => {
    const a = parsePreference(null);
    expect(Object.isFrozen(DEFAULT_PREFERENCE)).toBe(true);
    expect(a).toEqual(DEFAULT_PREFERENCE);
  });
});

describe("applyPreference", () => {
  it("sets both attributes on <html>, and removes data-theme for system so the OS decides", () => {
    applyPreference({ mode: "dark", accent: "slate" });
    expect(root().getAttribute("data-theme")).toBe("dark");
    expect(root().getAttribute("data-accent")).toBe("slate");
    applyPreference({ mode: "system", accent: "blue" });
    expect(root().hasAttribute("data-theme")).toBe(false);
    expect(root().getAttribute("data-accent")).toBe("blue");
  });
});

describe("theme-boot.js", () => {
  /** Runs the real boot script in this jsdom window, exactly as <head> would, after seeding storage. */
  function boot(stored: unknown) {
    localStorage.clear();
    root().removeAttribute("data-theme");
    root().removeAttribute("data-accent");
    if (stored !== undefined) localStorage.setItem(STORAGE_KEY, typeof stored === "string" ? stored : JSON.stringify(stored));
    new Function(bootScript)();
    return { theme: root().getAttribute("data-theme"), accent: root().getAttribute("data-accent") };
  }

  it("applies every saved mode and accent the app knows, before React runs", () => {
    for (const mode of MODES) {
      for (const accent of ACCENTS) {
        expect(boot({ mode, accent: accent.id })).toEqual({ theme: mode === "system" ? null : mode, accent: accent.id });
      }
    }
  });

  it("falls back to the OS theme and Blue for nothing, junk and unknown values", () => {
    expect(boot(undefined)).toEqual({ theme: null, accent: "blue" });
    expect(boot("{not json")).toEqual({ theme: null, accent: "blue" });
    expect(boot({ mode: "neon", accent: "pink" })).toEqual({ theme: null, accent: "blue" });
  });

  it("is plain ES5, so it runs before anything else on any browser", () => {
    expect(bootScript).not.toMatch(/\b(const|let|class)\b|=>|`/);
  });
});
