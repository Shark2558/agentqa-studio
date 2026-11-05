/** The help box's rules (pure, M1.4 Phase C): the pending list cleaned and capped as it arrives, how often to ask
 *  again, a click on a shown screenshot scaled to the agent's browser, and the bodies of answers and commands.
 *  Every part of a waiting question comes from the application under test: show it as text only. */
import { ApiError } from "./api";

export const CAPS = { question: 500, hint: 1000, option: 200, options: 20, clickables: 40, fields: 20, log: 12, line: 200, url: 2000, label: 200 } as const;
export const KEYS = ["Enter", "Tab", "Backspace", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Space"] as const;
export type Key = (typeof KEYS)[number];
export const LOG_SHOWN = 6;
export const TITLE = "(!) AgentQA needs you";
/** The name of a button, box or choice that has no words on it (the tested site gave none). */
export const NO_TEXT = "(no text)";
const TEXT_MAX = 200;
const TYPE_MAX = 500;
const PATH_MAX = 400;
const POINT_MAX = 10_000;
const SHOT_VERSION_MAX = 2 ** 31 - 1;          // a version counts up for as long as the question lives
const DEFAULT_VIEWPORT = { vw: 1280, vh: 800 } as const;
const SCROLL_DY = 400;
// Characters that turn text around or hide where it ends (display spoofing): the tested site's words never keep them.
const TURNS_TEXT = /[‪-‮⁦-⁩‎‏؜]/g;

export interface Spot { text: string; x: number; y: number }
export interface ScreenBox { label: string; type: string; x: number; y: number; filled: boolean }
export interface Waiting {
  id: number;
  kind: string;
  role: string | null;
  agent: string;
  at: string | null;
  /** False for someone who may only watch: the server sent who is waiting, never the screen. */
  full: boolean;
  question: string;
  hint: string;
  options: string[];
  clickables: Spot[];
  fields: ScreenBox[];
  secret: boolean;
  url: string;
  vw: number;
  vh: number;
  headed: boolean;
  log: string[];
  shotV: number;
  hasShot: boolean;
  production: boolean;
}
export interface Paused { on: boolean; at: string | null; by: string | null }
export interface Pending { items: Waiting[]; paused: Paused }

type Raw = Record<string, unknown>;
const isRaw = (v: unknown): v is Raw => typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown, max: number): string => (typeof v === "string" ? v.replace(TURNS_TEXT, "").slice(0, max) : "");
const nullable = (v: unknown, max: number): string | null => text(v, max) || null;
const coord = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= POINT_MAX ? v : null);
const version = (v: unknown): number => (typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= SHOT_VERSION_MAX ? v : 0);
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

function spots<T>(raw: unknown, max: number, shape: (r: Raw, x: number, y: number) => T): T[] {
  const out: T[] = [];
  for (const r of list(raw)) {
    const x = isRaw(r) ? coord(r.x) : null;
    const y = isRaw(r) ? coord(r.y) : null;
    if (isRaw(r) && x !== null && y !== null) out.push(shape(r, x, y));
  }
  return out.slice(0, max);
}

function waitingFrom(r: Raw): Waiting {
  return {
    id: r.id as number, kind: text(r.kind, 80), role: nullable(r.role, 80), agent: text(r.agent, 80), at: nullable(r.at, 40),
    full: "question" in r, question: text(r.question, CAPS.question), hint: text(r.hint, CAPS.hint),
    options: list(r.options).slice(0, CAPS.options).map((o) => text(o, CAPS.option)),
    clickables: spots(r.clickables, CAPS.clickables, (c, x, y) => ({ text: text(c.text, CAPS.label), x, y })),
    fields: spots(r.fields, CAPS.fields, (f, x, y) => ({ label: text(f.label, CAPS.label), type: text(f.type, 40), x, y, filled: f.filled === true })),
    secret: r.secret === true, url: text(r.url, CAPS.url), vw: coord(r.vw) || DEFAULT_VIEWPORT.vw, vh: coord(r.vh) || DEFAULT_VIEWPORT.vh,
    headed: r.headed === true, log: list(r.log).slice(-CAPS.log).map((l) => text(l, CAPS.line)), shotV: version(r.shot_v),
    hasShot: r.has_shot === true, production: r.production === true,
  };
}

/** The pending list as the page keeps it: only items with a whole id, every text capped, every point on a screen. */
export function cleanPending(raw: unknown): Pending {
  const body = isRaw(raw) ? raw : {};
  const items = list(body.items).filter((r): r is Raw => isRaw(r) && Number.isInteger(r.id)).map(waitingFrom);
  const p = isRaw(body.paused) ? body.paused : {};
  return { items, paused: { on: p.on === true, at: nullable(p.at, 40), by: nullable(p.by, CAPS.label) } };
}

/** "The explorer (as citizen)": who is waiting, in plain words. */
export function whoWaits(w: Pick<Waiting, "agent" | "role">): string {
  const name = w.agent ? `The ${w.agent}` : "An agent";
  return w.role ? `${name} (as ${w.role})` : name;
}

export const POLL = { visible: 2_000, takeover: 1_000, hidden: 10_000, error: 10_000 } as const;
const GIVE_UP = new Set([401, 403]);          // signed out, or not allowed: asking again cannot help (a 404 or 503 may pass)

/** How often to ask what is waiting: every 2 s while the tab is seen, every second during a take-over, every 10 s while
 *  the tab is hidden (so its title still changes), slower after a blip; never again once signed out or not allowed. */
export function pollMs(p: { visible: boolean; takingOver: boolean; error: unknown }): number | false {
  if (p.error instanceof ApiError && GIVE_UP.has(p.error.status)) return false;
  if (!p.visible) return POLL.hidden;
  if (p.error) return POLL.error;
  return p.takingOver ? POLL.takeover : POLL.visible;
}

export interface Point { x: number; y: number }

/** A click on the screenshot as shown (`shown` is the picture's own box on the page, not its button's) at the same
 *  place in the agent's browser; the last pixel of a screen is one short of its size, so a click is kept on it. */
export function scalePoint(click: Point, shown: { width: number; height: number }, screen: { vw: number; vh: number }): Point | null {
  if (!(shown.width > 0 && shown.height > 0)) return null;
  const clamp = (v: number) => Math.min(Math.max(v, 0), 1);
  const along = (share: number, size: number) => Math.min(Math.round(clamp(share) * size), Math.max(size - 1, 0));
  return { x: along(click.x / shown.width, screen.vw), y: along(click.y / shown.height, screen.vh) };
}

const isControl = (c: string): boolean => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127;

/** Control characters become spaces and nothing else changes: a typed password or code keeps every space it has. */
function noControls(value: string): string {
  return Array.from(value, (c) => (isControl(c) ? " " : c)).join("");
}

/** A label as one tidy line (words on a button, shown back to the person): control characters out, spaces collapsed. */
function oneLine(value: string): string {
  return noControls(value).replace(/\s+/g, " ").trim();
}

export type Answer = { text: string } | { option: number } | { x: number; y: number; text?: string } | { ok: boolean }
  | { skip: true } | { takeover: true } | { done: true };
export type AnswerKind = "text" | "option" | "point" | "ok" | "skip" | "takeover" | "done";

export const answer = {
  text: (value: string): Answer => ({ text: noControls(value).slice(0, TEXT_MAX) }),
  option: (n: number): Answer => ({ option: n }),
  point: (p: Point, label?: string): Answer => (label ? { x: p.x, y: p.y, text: oneLine(label).slice(0, TEXT_MAX) } : { x: p.x, y: p.y }),
  ok: (yes: boolean): Answer => ({ ok: yes }),
  skip: (): Answer => ({ skip: true }),
  takeover: (): Answer => ({ takeover: true }),
  done: (): Answer => ({ done: true }),
};

// Which answers each kind of question takes, as `orchestrator/gates/helpbox.py ANSWERS` says.
const TAKES: Readonly<Record<string, readonly AnswerKind[]>> = {
  takeover: ["done", "skip"], navigate: ["option", "point", "text", "takeover", "skip"], confirm: ["ok", "option", "skip"],
};
const OTHER_TAKES: readonly AnswerKind[] = ["text", "skip"];

export function takes(kind: string, action: AnswerKind): boolean {
  return (Object.hasOwn(TAKES, kind) ? TAKES[kind] : OTHER_TAKES).includes(action);
}

export type Command = { kind: "click"; x: number; y: number } | { kind: "type"; text: string; secret: boolean; replace: boolean }
  | { kind: "press"; key: Key } | { kind: "back" } | { kind: "scroll"; dy: number } | { kind: "goto"; path: string };

/** A password box is typed into as a secret even when "Hide what I type" is off (the agent checks again). */
export function isSecretBox(box: ScreenBox | null): boolean {
  return !!box && box.type.toLowerCase() === "password";
}

export const command = {
  click: (p: Point): Command => ({ kind: "click", x: p.x, y: p.y }),
  type: (value: string, o: { hide: boolean; box: ScreenBox | null; replace?: boolean }): Command => ({
    kind: "type", text: noControls(value).slice(0, TYPE_MAX), secret: o.hide || isSecretBox(o.box), replace: !!o.replace,
  }),
  press: (key: Key): Command => ({ kind: "press", key }),
  back: (): Command => ({ kind: "back" }),
  scroll: (dy = SCROLL_DY): Command => ({ kind: "scroll", dy }),
  scrollUp: (): Command => ({ kind: "scroll", dy: -SCROLL_DY }),
  goto: (path: string): Command => ({ kind: "goto", path }),
};

/** What a command did, in words for the status line (never the text typed: only how much). */
export function commandWords(c: Command): string {
  switch (c.kind) {
    case "click": return `Sent: click at (${c.x}, ${c.y})`;
    case "type": {
      const n = Array.from(c.text).length;
      return `Sent: typed ${n} character${n === 1 ? "" : "s"}`;
    }
    case "press": return `Sent: ${c.key}`;
    case "back": return "Sent: Back";
    case "scroll": return c.dy < 0 ? "Sent: Scroll up" : "Sent: Scroll down";
    case "goto": return `Sent: open ${c.path}`;
  }
}

/** A command after which the box that was selected may no longer be the one with the cursor in it. */
export function movesFocus(c: Command): boolean {
  return c.kind === "click" || c.kind === "goto" || c.kind === "back" || (c.kind === "press" && (c.key === "Tab" || c.key === "Enter"));
}

/** A path that stays a plain path of the portal once decoded (no `.` or `..` step, no `//`, no backslash): as the
 *  server reads it (`helpbox.py _in_scope`), so a refusal is said before anything is sent. */
function isPlainPath(path: string): boolean {
  let decoded = path.split(/[?#]/, 1)[0];
  try {
    decoded = decodeURIComponent(decoded);
  } catch {
    // not valid percent-encoding: the server keeps what it cannot read as it is, and so does this
  }
  const steps = decoded.split("/").slice(1);
  return !decoded.includes("\\") && !decoded.includes("//") && !steps.some((s) => s === "." || s === "..");
}

/** An address on the portal under test ("/apply", "@department/queue"), or null for anything else. */
export function portalPath(raw: string): string | null {
  const path = raw.trim();
  const ok = path.length > 0 && path.length <= PATH_MAX && /^[/@]/.test(path) && !Array.from(path).some(isControl) && isPlainPath(path);
  return ok ? path : null;
}
