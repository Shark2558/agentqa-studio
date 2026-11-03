/** Appearance: Light / Dark / System and one of five accents, chosen in the app and remembered per browser
 *  (per account once M2.1 brings team logins). public/theme-boot.js applies the saved choice before first paint
 *  with the same key and lists; theme.test.ts checks the two never drift. */
import { useSyncExternalStore } from "react";

export const MODES = ["light", "dark", "system"] as const;
export type Mode = (typeof MODES)[number];
export const MODE_LABELS: Record<Mode, string> = { light: "Light", dark: "Dark", system: "System" };
export const ACCENTS = [
  { id: "blue", label: "Blue", swatch: "#2563EB" },
  { id: "indigo", label: "Indigo", swatch: "#4F46E5" },
  { id: "teal", label: "Teal", swatch: "#0F766E" },
  { id: "green", label: "Green", swatch: "#15803D" },
  { id: "slate", label: "Slate", swatch: "#334155" },
] as const;
export type Accent = (typeof ACCENTS)[number]["id"];
export const STORAGE_KEY = "agentqa.theme";

export interface ThemePreference {
  mode: Mode;
  accent: Accent;
}

export const DEFAULT_PREFERENCE: ThemePreference = { mode: "system", accent: "blue" };
const MODE_SET: ReadonlySet<string> = new Set(MODES);
const ACCENT_SET: ReadonlySet<string> = new Set(ACCENTS.map((a) => a.id));

/** A stored value (JSON text or an object) checked against the allow-lists; anything else is the default. */
export function parsePreference(raw: unknown): ThemePreference {
  let data: unknown = raw;
  if (typeof raw === "string") {
    try {
      data = JSON.parse(raw);
    } catch {
      return DEFAULT_PREFERENCE;
    }
  }
  if (!data || typeof data !== "object") return DEFAULT_PREFERENCE;
  const { mode, accent } = data as Record<string, unknown>;
  return {
    mode: typeof mode === "string" && MODE_SET.has(mode) ? (mode as Mode) : DEFAULT_PREFERENCE.mode,
    accent: typeof accent === "string" && ACCENT_SET.has(accent) ? (accent as Accent) : DEFAULT_PREFERENCE.accent,
  };
}

function browserStorage(): Storage | undefined {
  try {
    return globalThis.localStorage;
  } catch {
    return undefined;                       // a locked-down browser: the choice lives for this page only
  }
}

export function loadPreference(storage: Storage | undefined = browserStorage()): ThemePreference {
  try {
    return parsePreference(storage?.getItem(STORAGE_KEY) ?? null);
  } catch {
    return DEFAULT_PREFERENCE;
  }
}

export function savePreference(pref: ThemePreference, storage: Storage | undefined = browserStorage()): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(pref));
  } catch {
    // private window or full storage: the page still shows the choice, it is just not remembered
  }
}

/** Both attributes go on <html>, where the accent blocks in tokens.css resolve; `system` removes data-theme so the OS decides. */
export function applyPreference(pref: ThemePreference, el: HTMLElement = document.documentElement): void {
  if (pref.mode === "system") el.removeAttribute("data-theme");
  else el.setAttribute("data-theme", pref.mode);
  el.setAttribute("data-accent", pref.accent);
}

// ---- the store behind useTheme: one value, applied and saved on change, following other tabs ----------------
const listeners = new Set<() => void>();
let current: ThemePreference | null = null;

function snapshot(): ThemePreference {
  if (current === null) current = loadPreference();
  return current;
}

export function setPreference(pref: ThemePreference): void {
  current = pref;
  applyPreference(pref);
  savePreference(pref);
  listeners.forEach((notify) => notify());
}

function subscribe(notify: () => void): () => void {
  current = loadPreference();                         // a fresh mount reads what the boot script applied
  listeners.add(notify);
  const onStorage = (e: StorageEvent) => {
    if (e.key !== null && e.key !== STORAGE_KEY) return;
    current = loadPreference();
    applyPreference(current);
    notify();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(notify);
    window.removeEventListener("storage", onStorage);
  };
}

export function useTheme(): [ThemePreference, (pref: ThemePreference) => void] {
  const pref = useSyncExternalStore(subscribe, snapshot, () => DEFAULT_PREFERENCE);
  return [pref, setPreference];
}
