/** The Live View's whole picture at a point in a run: board, browser frames, panels and site map, folded event by
 *  event. Folding is pure (a model is never changed), so a checkpoint every 500 events costs nothing to keep and
 *  jumping anywhere in a replay is "nearest checkpoint, then fold the rest". Live and replay share this one fold, which
 *  is what makes a replay match what was watched live. */
import { displayState, emptyBoard, foldBoard, type BoardDef, type BoardModel } from "./board";
import type { LiveEvent } from "./event";
import { emptyLanes, foldLanes, type LanesModel } from "./lanes";
import { emptyPanels, foldPanels, tileCounts, type PanelsModel } from "./panels";
import { emptyMap, foldMap, type SiteMap } from "./siteMap";

export const CHECKPOINT_EVERY = 500;

export interface Model {
  readonly board: BoardModel;
  readonly lanes: LanesModel;
  readonly panels: PanelsModel;
  readonly map: SiteMap;
  readonly count: number;
}

export interface Timeline {
  readonly checkpoints: readonly Model[];
}

export function emptyModel(def: BoardDef): Model {
  return { board: emptyBoard(def), lanes: emptyLanes, panels: emptyPanels, map: emptyMap, count: 0 };
}

export function fold(model: Model, events: readonly LiveEvent[], def: BoardDef): Model {
  if (events.length === 0) return model;
  return {
    board: foldBoard(model.board, events, def),
    lanes: foldLanes(model.lanes, events),
    panels: foldPanels(model.panels, events),
    map: foldMap(model.map, events),
    count: model.count + events.length,
  };
}

/** Checkpoints for `events`; with a previous timeline, the ones before `changedFrom` are kept as they are. */
export function buildTimeline(events: readonly LiveEvent[], def: BoardDef, previous?: Timeline, changedFrom = 0): Timeline {
  const kept = previous ? previous.checkpoints.filter((_, k) => k * CHECKPOINT_EVERY <= changedFrom) : [];
  const checkpoints = kept.length ? [...kept] : [emptyModel(def)];
  let model = checkpoints[checkpoints.length - 1];
  for (let end = checkpoints.length * CHECKPOINT_EVERY; end <= events.length; end += CHECKPOINT_EVERY) {
    model = fold(model, events.slice(end - CHECKPOINT_EVERY, end), def);
    checkpoints.push(model);
  }
  return { checkpoints };
}

/** The model after the first `pos` events. */
export function modelAt(timeline: Timeline, events: readonly LiveEvent[], pos: number, def: BoardDef): Model {
  const end = Math.max(0, Math.min(pos, events.length));
  const k = Math.min(Math.floor(end / CHECKPOINT_EVERY), timeline.checkpoints.length - 1);
  return fold(timeline.checkpoints[k], events.slice(k * CHECKPOINT_EVERY, end), def);
}

/** A plain, comparable copy of a model (Maps and Sets as arrays), for tests and the browser checks. */
export function snapshot(value: unknown): unknown {
  if (value instanceof Map) return [...value.entries()].map(([k, v]) => [k, snapshot(v)]);
  if (value instanceof Set) return [...value].map(snapshot);
  if (Array.isArray(value)) return value.map(snapshot);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, snapshot(v)]));
  return value;
}

const round4 = (n: number) => Math.round(n * 10_000) / 10_000;

export interface Summary {
  cards: Record<string, { state: string; cost: number; model: string | null }>;
  gates: BoardModel["gates"];
  tiles: Record<string, number>;
  ai: { calls: number; cost: number };
}

/** The final picture in a few numbers: each stage's state, cost and model, the gates, the tiles and the AI totals. */
export function summarize(model: Model, runOver: boolean): Summary {
  const b = model.board;
  const cards = Object.fromEntries(
    b.order.flatMap((agent) => {
      const c = b.cards.get(agent);
      return c && c.stage ? [[agent, { state: displayState(c, b, runOver), cost: round4(c.cost), model: c.actualModel }]] : [];
    }),
  );
  return { cards, gates: { ...b.gates }, tiles: tileCounts(model.panels, runOver), ai: { calls: b.ai.calls, cost: round4(b.ai.cost) } };
}
