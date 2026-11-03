/** One live event as the API serves it, checked at the boundary. Everything in an event comes from the run, and much of
 *  it from the application under test (page titles, URLs, document text, model rewrites): it is data, shown as text,
 *  never markup, never a link. Reading a field goes through the helpers here, which check its type. */

export type Phase = "thought" | "action" | "result" | "waiting" | "lifecycle" | "meta" | "note";
export const PHASES: readonly Phase[] = ["thought", "action", "result", "waiting", "lifecycle", "meta", "note"];

export interface LiveEvent {
  readonly t: number;
  readonly seq: number;
  readonly w: string;
  readonly agent: string;
  readonly kind: string;
  readonly title: string;
  readonly phase: Phase;
  readonly level?: string | number;
  readonly [key: string]: unknown;
}

export type Severity = "ok" | "warn" | "bad";

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
  vw: number;
  vh: number;
}

const DEFAULT_VW = 1280;
const DEFAULT_VH = 720;
const MAX_VIEWPORT = 10_000;
const SHOT_NAME = /^[\w.-]{1,80}\.jpg$/;
const MAX_LIST = 50;
// What one event may carry (security review: a hostile application must not be able to freeze or fill the tab).
const MAX_TITLE = 500;
const MAX_PREVIEW = 20_000;        // a generated test file's first lines
const MAX_TEXT = 2_000;
const MAX_NAME = 64;               // worker, agent, kind, and every key
const MAX_ITEMS = 200;             // per list and per object
const MAX_DEPTH = 3;
const MAX_T = 4e9;                 // seconds: the year 2096; a larger time breaks every clock on the page
const LIMITS: Readonly<Record<string, number>> = { title: MAX_TITLE, preview: MAX_PREVIEW, w: MAX_NAME, agent: MAX_NAME, kind: MAX_NAME };

const isText = (v: unknown): v is string => typeof v === "string";
const isFiniteNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** Sets `key` as a plain own property, so a key named __proto__ is only data. */
function put(out: Record<string, unknown>, key: string, value: unknown): void {
  Object.defineProperty(out, key, { value, enumerable: true, writable: true, configurable: true });
}

/** A copy of untrusted JSON with every text cut to `max`, lists and objects to 200 items and three levels, and
 *  anything that is not text, a finite number, true / false or null left out. */
function clean(value: unknown, max: number, depth: number): unknown {
  if (isText(value)) return value.length > max ? value.slice(0, max) : value;
  if (isFiniteNumber(value) || typeof value === "boolean" || value === null) return value;
  if (!value || typeof value !== "object") return undefined;
  if (Array.isArray(value)) {
    return depth > 0 ? value.slice(0, MAX_ITEMS).map((v) => clean(v, MAX_TEXT, depth - 1)).filter((v) => v !== undefined) : [];
  }
  const out: Record<string, unknown> = {};
  if (depth <= 0) return out;
  for (const [k, v] of Object.entries(value).slice(0, MAX_ITEMS)) {
    const c = clean(v, MAX_TEXT, depth - 1);
    if (c !== undefined) put(out, k.slice(0, MAX_NAME), c);
  }
  return out;
}

/** The event, with its phase checked (an unknown phase is a note), or null when it is not shaped like one. Its text
 *  is cut to size and its nested data kept shallow (see clean). */
export function toEvent(x: unknown): LiveEvent | null {
  if (!x || typeof x !== "object" || Array.isArray(x)) return null;
  const e = x as Record<string, unknown>;
  if (!isFiniteNumber(e.t) || e.t < 0 || e.t > MAX_T || !Number.isInteger(e.seq) || (e.seq as number) < 0) return null;
  if (!isText(e.w) || !isText(e.agent) || !isText(e.kind) || !isText(e.title)) return null;
  const phase = PHASES.includes(e.phase as Phase) ? (e.phase as Phase) : "note";
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(e).slice(0, MAX_ITEMS)) {
    const c = clean(v, Object.hasOwn(LIMITS, k) ? LIMITS[k] : MAX_TEXT, MAX_DEPTH);
    if (c !== undefined) put(out, k.slice(0, MAX_NAME), c);
  }
  put(out, "phase", phase);
  return out as unknown as LiveEvent;
}

export const eventKey = (e: LiveEvent): string => `${e.w}:${e.seq}`;

/** One order for live and replay: time, then sequence, then worker. */
export function compareEvents(a: LiveEvent, b: LiveEvent): number {
  return a.t - b.t || a.seq - b.seq || (a.w < b.w ? -1 : a.w > b.w ? 1 : 0);
}

export function severity(e: LiveEvent): Severity | null {
  return e.level === "ok" || e.level === "warn" || e.level === "bad" ? e.level : null;
}

/** A text field, or undefined when the event has none (or something that is not text). */
export function text(e: LiveEvent, key: string): string | undefined {
  const v = e[key];
  return isText(v) ? v : undefined;
}

/** A finite number field, or undefined. */
export function num(e: LiveEvent, key: string): number | undefined {
  const v = e[key];
  return isFiniteNumber(v) ? v : undefined;
}

/** A list of text, keeping only the text items (at most 50). */
export function texts(e: LiveEvent, key: string): string[] {
  const v = e[key];
  return Array.isArray(v) ? v.filter(isText).slice(0, MAX_LIST) : [];
}

/** A screenshot name the server could have written: a plain `.jpg` file name, nothing that walks a path. */
export function safeShot(name: unknown): string | null {
  return isText(name) && SHOT_NAME.test(name) ? name : null;
}

/** The outlined element's box, from finite numbers only, starting inside the viewport; otherwise null. */
export function safeBox(e: LiveEvent): Box | null {
  const b = e.box;
  if (!b || typeof b !== "object") return null;
  const { x, y, width, height } = b as Record<string, unknown>;
  if (![x, y, width, height].every(isFiniteNumber)) return null;
  const vw = num(e, "vw") ?? DEFAULT_VW;
  const vh = num(e, "vh") ?? DEFAULT_VH;
  const box = { x: x as number, y: y as number, width: width as number, height: height as number, vw, vh };
  if (box.x < 0 || box.y < 0 || box.width <= 0 || box.height <= 0 || vw <= 0 || vh <= 0) return null;
  if (vw > MAX_VIEWPORT || vh > MAX_VIEWPORT) return null;
  return box.x < vw && box.y < vh ? box : null;
}
