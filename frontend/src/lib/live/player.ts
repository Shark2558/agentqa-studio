/** Replay: where in the run the picture is, whether it plays, how fast, and whether it follows the newest event.
 *  `dwellMs` is the v0.8 player's pacing (a screenshot lingers, a rule flashes by), and a viewer following a live run
 *  catches up when events pile up. A finished run opens at its final picture (owner decision 4, M1.3); the position
 *  is remembered per run for this tab only. */
import { safeShot, type LiveEvent } from "./event";

export type Speed = 0.5 | 1 | 2 | 4 | 10 | 0;
export const SPEEDS: readonly Speed[] = [0.5, 1, 2, 4, 10, 0];
export const INSTANT_STEP = 600;                 // events applied per tick at "instant"
const REPLAY_SPEED: Speed = 2;
const BACKLOG_CATCH_UP = 40;
const MAX_CATCH_UP = 25;

export interface Player {
  readonly pos: number;
  readonly playing: boolean;
  readonly speed: Speed;
  readonly follow: boolean;
}

export type PlayerAction =
  | { type: "play" }
  | { type: "pause" }
  | { type: "toggle" }
  | { type: "step"; total: number }
  | { type: "restart" }
  | { type: "live"; total: number }
  | { type: "scrub"; pos: number; total: number }
  | { type: "speed"; speed: Speed }
  | { type: "advance"; by: number; total: number }
  | { type: "settle"; total: number; saved: { pos: number; follow: boolean } | null }   // a finished run, once its events are in
  | { type: "shift"; by: number };                                                        // the oldest `by` events were dropped

const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));

export function playerReducer(p: Player, a: PlayerAction): Player {
  switch (a.type) {
    case "play": return { ...p, playing: true };
    case "pause": return { ...p, playing: false };
    case "toggle": return { ...p, playing: !p.playing };
    case "step": return { ...p, pos: clamp(p.pos + 1, 0, a.total), playing: false };
    case "restart": return { ...p, pos: 0, playing: true, follow: false };
    case "live": return { ...p, pos: a.total, playing: true, follow: true };
    case "scrub": return { ...p, pos: clamp(Math.round(a.pos), 0, a.total), playing: false, follow: false };
    case "speed": return { ...p, speed: a.speed };
    case "advance": return { ...p, pos: clamp(p.pos + a.by, 0, a.total) };
    case "settle": return initialPlayer(a.total, false, a.saved);
    case "shift": return { ...p, pos: Math.max(0, p.pos - a.by) };
  }
}

const LINGER: readonly [readonly string[], number][] = [
  [["requirement", "text", "heading", "table"], 300],
  [["rule", "status", "case", "request"], 55],
  [["test_start", "test_end", "verdict"], 160],
  [["stage_start", "stage_end", "gate", "summary", "defect", "question"], 450],
];

/** How long replay stays on `e` before the next event. */
export function dwellMs(e: LiveEvent, speed: Speed, backlog: number, follow: boolean): number {
  if (speed === 0) return 0;
  let ms = safeShot(e.shot) ? 650 : (LINGER.find(([kinds]) => kinds.includes(e.kind))?.[1] ?? 120);
  if (follow && backlog > BACKLOG_CATCH_UP) ms /= Math.min(MAX_CATCH_UP, backlog / 12);
  return ms / speed;
}

/** Where a run opens: a running run follows live; a finished one shows its final picture (or this viewer's spot). */
export function initialPlayer(total: number, running: boolean, saved: { pos: number; follow: boolean } | null): Player {
  if (running) return { pos: total, playing: true, speed: 1, follow: true };
  return { pos: saved ? clamp(saved.pos, 0, total) : total, playing: false, speed: REPLAY_SPEED, follow: false };
}

const storageKey = (project: string, session: string) => `agentqa.live.${project}.${session}`;

export function savePosition(project: string, session: string, p: Player): void {
  try {
    sessionStorage.setItem(storageKey(project, session), JSON.stringify({ pos: p.pos, follow: p.follow }));
  } catch {
    // storage refused (private mode, quota): the position is a convenience, the page works without it
  }
}

export function loadPosition(project: string, session: string): { pos: number; follow: boolean } | null {
  try {
    const raw: unknown = JSON.parse(sessionStorage.getItem(storageKey(project, session)) ?? "null");
    if (!raw || typeof raw !== "object") return null;
    const { pos, follow } = raw as Record<string, unknown>;
    return Number.isInteger(pos) && (pos as number) >= 0 && typeof follow === "boolean" ? { pos: pos as number, follow } : null;
  } catch {
    return null;
  }
}
