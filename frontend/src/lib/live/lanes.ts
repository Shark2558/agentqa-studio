/** One browser frame per worker (ported from the v0.8 player's lanes): the newest screenshot, the element being acted
 *  on, the address, role and test case, the last six steps and the verdict. Screenshot names and boxes are checked
 *  (`safeShot`, `safeBox`); the address is shown as text, never followed. */
import { safeBox, safeShot, text, type Box, type LiveEvent } from "./event";

const BROWSER_AGENTS = new Set(["explorer", "exploratory", "executor", "healer", "security"]);
const BROWSER_KINDS = new Set(["navigate", "action", "observe", "verdict", "request", "test_start", "test_end", "step", "login", "finding"]);
const STEPS_KEPT = 6;

export interface Lane {
  readonly key: string;
  readonly agent: string;
  readonly url: string;
  readonly role: string;
  readonly case: string;
  readonly shot: string | null;
  readonly box: Box | null;
  readonly caption: string;
  readonly kind: string;
  readonly steps: readonly string[];
  readonly verdict: { level: "ok" | "bad"; text: string } | null;
  readonly lastT: number;
}

export interface LanesModel {
  readonly lanes: ReadonlyMap<string, Lane>;
  readonly order: readonly string[];
}

export const emptyLanes: LanesModel = { lanes: new Map(), order: [] };

function blank(key: string, agent: string): Lane {
  return { key, agent, url: "", role: "", case: "", shot: null, box: null, caption: "", kind: "", steps: [], verdict: null, lastT: 0 };
}

function next(lane: Lane, e: LiveEvent): Lane {
  const restart = e.kind === "test_start";
  const shot = safeShot(e.shot);
  const caseId = text(e, "case") ?? (restart ? "" : lane.case);
  const pictured = shot ? { shot, box: safeBox(e) } : e.kind === "action" || e.kind === "navigate" ? { box: null } : {};
  const steps = restart ? [] : lane.steps;
  const verdict = e.kind === "verdict" ? { level: e.level === "ok" ? ("ok" as const) : ("bad" as const), text: e.title }
                                       : restart ? null : lane.verdict;
  const narrated = e.kind === "test_end" ? {} : { caption: e.title, kind: e.kind, steps: [e.title, ...steps].slice(0, STEPS_KEPT) };
  return { ...lane, agent: e.agent, url: text(e, "url") ?? lane.url, role: text(e, "role") ?? lane.role, case: caseId,
           steps, verdict, lastT: e.t, ...pictured, ...narrated };
}

export function foldLanes(model: LanesModel, events: readonly LiveEvent[]): LanesModel {
  let lanes: Map<string, Lane> | null = null;
  let order: string[] | null = null;
  for (const e of events) {
    if (!BROWSER_AGENTS.has(e.agent) || !BROWSER_KINDS.has(e.kind)) continue;
    lanes = lanes ?? new Map(model.lanes);
    order = order ?? [...model.order];
    const known = lanes.get(e.w);
    if (!known) order.push(e.w);
    lanes.set(e.w, next(known ?? blank(e.w, e.agent), e));
  }
  return lanes && order ? { lanes, order } : model;
}
