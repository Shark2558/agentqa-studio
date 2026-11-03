/** The agent board: one card per stage in pipeline order (from the server's board, `GET /live/board`), plus a card for
 *  any other agent that speaks. Helper agents, model choices, model costs and provider switches are credited to the
 *  stage running at the time. A card keeps its raw state; what it shows once the run is over ("not reached", "did not
 *  finish") is worked out when drawn, so a live run and its replay fold to the same model. */
import { eventKey, num, text, texts, type LiveEvent } from "./event";

export interface BoardDef {
  stages: readonly { stage: string; agent: string; label: string }[];
  helpers: Readonly<Record<string, readonly string[]>>;
  helper_fallback: Readonly<Record<string, string>>;
  labels: Readonly<Record<string, string>>;
  gates: readonly { id: string; label: string; after?: string; before?: string }[];
  ai_labels: Readonly<Record<string, string>>;
  roles: readonly string[];
}

export type RawState = "queued" | "running" | "waiting" | "done" | "skipped" | "failed";
export type CardState = RawState | "not-in-run" | "not-reached" | "did-not-finish";
export type PlanGate = "pending" | "approved" | "waiting";

export interface Card {
  readonly agent: string;
  readonly label: string;
  readonly stage: string | null;
  readonly extra: boolean;
  readonly state: RawState;
  readonly startedAt: number | null;
  readonly endedAt: number | null;
  readonly waitingSince: number | null;
  readonly counters: Readonly<Record<string, number>>;
  readonly events: number;
  readonly last: string;
  readonly helpers: readonly string[];
  readonly cost: number;
  readonly tokensIn: number;
  readonly tokensOut: number;
  readonly actualModel: string | null;
  readonly models: readonly string[];
  readonly switchLines: ReadonlySet<string>;
  readonly planned: ReadonlyMap<string, string>;
  readonly reasons: ReadonlyMap<string, string>;
  readonly skipWhy: string | null;
  readonly error: string | null;
}

export interface BoardModel {
  readonly cards: ReadonlyMap<string, Card>;
  readonly order: readonly string[];
  readonly running: string | null;
  readonly runStages: readonly string[] | null;
  readonly pipelineId: string | null;
  readonly roles: readonly string[];
  readonly ended: { outcome: string; level: string } | null;
  readonly gates: { questions: number; plan: PlanGate; defects: number };
  readonly ai: { calls: number; cost: number; tokensIn: number; tokensOut: number };
  readonly assists: ReadonlyMap<string, string>;
  readonly t0: number | null;
  readonly tLast: number | null;
}

type Draft = { -readonly [K in keyof BoardModel]: BoardModel[K] } & { cards: Map<string, Card>; order: string[]; assists: Map<string, string> };

interface Ctx {
  def: BoardDef;
  stageOf: Map<string, string>;
  agentOfStage: Map<string, string>;
  helpers: Set<string>;
}

const contexts = new WeakMap<BoardDef, Ctx>();
const own = <T>(rec: Readonly<Record<string, T>>, key: string): T | undefined => (Object.hasOwn(rec, key) ? rec[key] : undefined);
// A stream that invents names must not grow the board without end (security review).
const MAX_CARDS = 40;
const MAX_ASSISTS = 200;
const MAX_MODEL_KEYS = 20;
const MAX_MODELS = 20;
const MAX_SWITCH_LINES = 50;
const SHOWN_MODELS = 2;                    // the cards are narrow: two names, then "and N more"
const MAX_MODEL_NAME = 60;                 // a name from a provider's model list is cut to fit a card
const atLeastZero = (n: number | undefined): number => Math.max(0, n ?? 0);

function context(def: BoardDef): Ctx {
  const known = contexts.get(def);
  if (known) return known;
  const ctx: Ctx = {
    def,
    stageOf: new Map(def.stages.map((s) => [s.agent, s.stage])),
    agentOfStage: new Map(def.stages.map((s) => [s.stage, s.agent])),
    helpers: new Set(Object.values(def.helpers).flat()),
  };
  contexts.set(def, ctx);
  return ctx;
}

function newCard(agent: string, label: string, stage: string | null, extra: boolean): Card {
  return {
    agent, label, stage, extra, state: "queued", startedAt: null, endedAt: null, waitingSince: null, counters: {},
    events: 0, last: "", helpers: [], cost: 0, tokensIn: 0, tokensOut: 0, actualModel: null, models: [],
    switchLines: new Set(), planned: new Map(), reasons: new Map(), skipWhy: null, error: null,
  };
}

export function emptyBoard(def: BoardDef): BoardModel {
  const cards = new Map(def.stages.map((s) => [s.agent, newCard(s.agent, own(def.labels, s.agent) ?? s.label, s.stage, false)]));
  return {
    cards, order: def.stages.map((s) => s.agent), running: null, runStages: null, pipelineId: null, roles: [...def.roles],
    ended: null, gates: { questions: 0, plan: "pending", defects: 0 }, ai: { calls: 0, cost: 0, tokensIn: 0, tokensOut: 0 },
    assists: new Map(), t0: null, tLast: null,
  };
}

/** The agent's card, made on its first word; null once the board holds 40 cards (the rest are not shown). */
function cardOf(d: Draft, agent: string, ctx: Ctx): Card | null {
  const known = d.cards.get(agent);
  if (known) return known;
  if (d.cards.size >= MAX_CARDS) return null;
  const made = newCard(agent, own(ctx.def.labels, agent) ?? agent, null, true);
  d.cards.set(agent, made);
  d.order.push(agent);
  return made;
}

function update(d: Draft, agent: string, ctx: Ctx, change: (c: Card) => Partial<Card>): void {
  const c = cardOf(d, agent, ctx);
  if (c) d.cards.set(agent, { ...c, ...change(c) });
}

/** `map` with `key` set, unless it would grow past 20 keys. */
const keyed = (map: ReadonlyMap<string, string>, key: string, value: string): ReadonlyMap<string, string> =>
  map.has(key) || map.size < MAX_MODEL_KEYS ? new Map(map).set(key, value) : map;

/** `models` with `model` at the end, unless it is there already or the list holds 20. */
const withModel = (models: readonly string[], model: string | undefined): readonly string[] =>
  !model || models.includes(model) || models.length >= MAX_MODELS ? models : [...models, model];

/** `lines` with `key` added, unless it would hold more than 50. */
const withLine = (lines: ReadonlySet<string>, key: string): ReadonlySet<string> =>
  lines.has(key) || lines.size >= MAX_SWITCH_LINES ? lines : new Set(lines).add(key);

/** The card an event counts for: a helper (Analyst, Test Case Generator, Importer) works for the stage running now. */
function targetOf(d: Draft, agent: string, ctx: Ctx): string {
  if (!ctx.helpers.has(agent)) return agent;
  const fallback = own(ctx.def.helper_fallback, agent);
  return d.running ?? (fallback ? ctx.agentOfStage.get(fallback) : undefined) ?? agent;
}

function onStage(d: Draft, e: LiveEvent, ctx: Ctx): void {
  if (e.kind === "stage_start") {
    update(d, e.agent, ctx, () => ({ state: "running", startedAt: e.t, endedAt: null, error: null }));
    d.running = e.agent;
  } else if (e.kind === "stage_end") {
    const failed = e.level === "bad";
    update(d, e.agent, ctx, () => ({ state: failed ? "failed" : "done", endedAt: e.t, waitingSince: null,
                                      error: failed ? (text(e, "error") ?? null) : null }));
    if (d.running === e.agent) d.running = null;
  } else {
    update(d, e.agent, ctx, () => ({ state: "skipped", skipWhy: text(e, "why") ?? null }));
  }
}

function onPipeline(d: Draft, e: LiveEvent, ctx: Ctx): void {
  if (e.kind === "stage_start") {
    const stages = texts(e, "stages");
    d.runStages = stages.length ? stages : null;
    d.pipelineId = text(e, "pipeline") ?? null;
    if (Array.isArray(e.roles)) d.roles = texts(e, "roles");
  } else if (e.kind === "stage_end") {
    d.ended = { outcome: text(e, "outcome") ?? "finished", level: typeof e.level === "string" ? e.level : "ok" };
  } else if (e.kind === "gate" && e.title.includes("plan gate")) {      // the only gate that stops the pipeline
    d.gates = { ...d.gates, plan: "waiting" };
    const generator = ctx.agentOfStage.get("generate");
    if (generator) update(d, generator, ctx, () => ({ state: "waiting", waitingSince: e.t }));
  }
}

function onAi(d: Draft, e: LiveEvent, ctx: Ctx): void {
  const key = text(e, "agent_key") ?? "?";
  if (e.kind === "cost") {
    if (num(e, "cost_usd") === undefined) return;
    const cost = atLeastZero(num(e, "cost_usd"));            // a negative cost must never lower the spend shown
    const tin = atLeastZero(num(e, "input_tokens"));
    const tout = atLeastZero(num(e, "output_tokens"));
    d.ai = { calls: d.ai.calls + 1, cost: d.ai.cost + cost, tokensIn: d.ai.tokensIn + tin, tokensOut: d.ai.tokensOut + tout };
    const model = text(e, "model");
    if (d.running) update(d, d.running, ctx, (c) => ({ cost: c.cost + cost, tokensIn: c.tokensIn + tin, tokensOut: c.tokensOut + tout,
                                                      actualModel: model ?? c.actualModel, models: withModel(c.models, model) }));
  } else if (e.kind === "switched" && d.running) {
    update(d, d.running, ctx, (c) => ({ switchLines: withLine(c.switchLines, eventKey(e)) }));
  } else if (e.kind === "model" && d.running) {
    const reason = text(e, "reason");
    const planned = e.title.includes(": ") ? e.title.slice(e.title.indexOf(": ") + 2) : e.title;
    update(d, d.running, ctx, (c) => (reason ? { reasons: keyed(c.reasons, key, reason) } : { planned: keyed(c.planned, key, planned) }));
  }
}

function onAssist(d: Draft, e: LiveEvent, agent: string, ctx: Ctx): void {
  const id = text(e, "assist_id");
  if (!id) return;
  if (!d.assists.has(id)) {
    if (d.assists.size >= MAX_ASSISTS) return;
    d.assists.set(id, agent);
    update(d, agent, ctx, () => ({ state: "waiting", waitingSince: e.t }));
    return;
  }
  d.assists.delete(id);
  const stillWaiting = [...d.assists.values()].includes(agent);
  update(d, agent, ctx, (c) => (c.state === "waiting" && !stillWaiting ? { state: "running", waitingSince: null } : {}));
}

const COUNTER: Readonly<Record<string, string>> = {
  "srs:requirement": "requirements", "srs:rule": "rules", "srs:ambiguity": "vague", "srs:unclear": "vague",
  "explorer:navigate": "screens", "reconciler:status": "checked", "reconciler:question": "questions",
  "writer:requirement": "rewritten", "designer:case": "cases", "generator:write": "files",
  "exploratory:navigate": "pages", "exploratory:finding": "findings", "triage:defect": "defects",
  "healer:heal": "proposals", "reporter:write": "reports",
};
const TEST_RESULTS = new Set(["passed", "defect", "visual", "blocked", "not-run", "test-issue"]);

function counted(c: Card, e: LiveEvent): Record<string, number> {
  const next = { ...c.counters };
  const add = (name: string, by = 1) => { next[name] = Math.max(0, (Object.hasOwn(next, name) ? next[name] : 0) + by); };
  const name = own(COUNTER, `${e.agent}:${e.kind}`);
  if (name) add(name);
  if (e.agent === "writer" && e.kind === "requirement" && texts(e, "flags").length) add("flagged");
  if (e.agent === "generator" && e.kind === "write") add("tests", num(e, "tests") ?? 0);
  if (e.agent === "security" && e.kind === "summary") next.alerts = atLeastZero(num(e, "alerts") ?? next.alerts);
  if (e.agent === "executor" && e.kind === "test_start") add("running");
  if (e.agent === "executor" && e.kind === "test_end") {
    add("running", -1);
    const category = text(e, "category");
    if (category && TEST_RESULTS.has(category)) add(category);
  }
  return next;
}

function apply(d: Draft, e: LiveEvent, ctx: Ctx): void {
  d.t0 = d.t0 ?? e.t;
  d.tLast = e.t;
  if (e.agent === "pipeline") return onPipeline(d, e, ctx);
  if (e.agent === "ai") return onAi(d, e, ctx);
  const agent = targetOf(d, e.agent, ctx);
  if (agent === e.agent && (e.kind === "stage_start" || e.kind === "stage_end" || e.kind === "stage_skip")) onStage(d, e, ctx);
  if (e.kind === "assist") onAssist(d, e, agent, ctx);
  if (e.kind === "question") d.gates = { ...d.gates, questions: d.gates.questions + 1 };
  if (e.kind === "defect" && e.agent === "triage") d.gates = { ...d.gates, defects: d.gates.defects + 1 };
  if (e.kind === "approve" && e.agent === "designer") d.gates = { ...d.gates, plan: "approved" };
  update(d, agent, ctx, (c) => ({
    counters: counted(c, e), events: c.events + 1, last: e.title,
    helpers: agent !== e.agent && !c.helpers.includes(e.agent) ? [...c.helpers, e.agent] : c.helpers,
  }));
}

/** The board after `events`; the board given is never changed. */
export function foldBoard(board: BoardModel, events: readonly LiveEvent[], def: BoardDef): BoardModel {
  if (events.length === 0) return board;
  const ctx = context(def);
  const d: Draft = { ...board, cards: new Map(board.cards), order: [...board.order], assists: new Map(board.assists) };
  for (const e of events) apply(d, e, ctx);
  return d;
}

/** What a card shows: its own state, or how the run left it once the run is over. */
export function displayState(card: Card, board: BoardModel, runOver: boolean): CardState {
  if (card.state === "queued" && board.runStages && card.stage && !board.runStages.includes(card.stage)) return "not-in-run";
  if (!runOver) return card.state;
  if (card.state === "running") return "did-not-finish";
  if (card.state === "queued") return "not-reached";
  return card.state;
}

const SHOWN: Readonly<Record<string, readonly (readonly [string, string])[]>> = {
  srs: [["requirements", "requirements"], ["rules", "rules"], ["vague", "vague"]],
  explorer: [["screens", "screens mapped"]],
  reconciler: [["checked", "rules checked"], ["questions", "questions for you"]],
  writer: [["rewritten", "rewritten"], ["flagged", "flagged"]],
  designer: [["cases", "cases"]],
  generator: [["files", "files"], ["tests", "tests"]],
  executor: [["passed", "passed"], ["defect", "failed"], ["blocked", "blocked"], ["running", "running"]],
  exploratory: [["pages", "pages"], ["findings", "findings"]],
  security: [["alerts", "alerts"]],
  triage: [["defects", "defects"]],
  healer: [["proposals", "proposals"]],
  reporter: [["reports", "report ready"]],
};

/** The card's live counters in words ("45 requirements · 48 rules"), or how many events it sent. */
export function counterText(card: Card): string {
  const parts = (own(SHOWN, card.agent) ?? [])
    .filter(([key]) => Object.hasOwn(card.counters, key) && card.counters[key] > 0)
    .map(([key, words]) => `${card.counters[key]} ${words}`);
  if (parts.length) return parts.join(" · ");
  return card.events ? `${card.events} event${card.events === 1 ? "" : "s"}` : "";
}

/** The model line: the models that answered (two by name, then how many more), else the one planned, else why there
 *  is none. */
export function cardModel(card: Card): string {
  if (card.models.length) {
    const short = (m: string) => (m.length > MAX_MODEL_NAME ? `${m.slice(0, MAX_MODEL_NAME - 1)}…` : m);
    const named = card.models.slice(0, SHOWN_MODELS).map(short).join(", ");
    const more = card.models.length - SHOWN_MODELS;
    return more > 0 ? `${named} and ${more} more` : named;
  }
  const planned = [...card.planned.values()][0];
  if (planned) return planned;
  const reason = [...card.reasons.values()][0];
  return reason ? `no AI: ${reason}` : "";
}
