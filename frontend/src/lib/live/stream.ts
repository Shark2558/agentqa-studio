/** The events of one run as they arrive: each once (a reconnect may send some again), always in (time, seq, worker)
 *  order whatever worker file they came from, at most the newest 50 000. `changedFrom` says where the order changed,
 *  so the model is recomputed from there and not from the start. Past 50 000 the oldest go in whole blocks of 500
 *  (`dropped` counts them), so the timeline keeps the checkpoint at that boundary and its totals stay exact. */
import { compareEvents, eventKey, toEvent, type LiveEvent } from "./event";

export const MAX_EVENTS = 50_000;
export const DROP_BLOCK = 500;                 // the model's CHECKPOINT_EVERY
export type EndReason = "finished" | "idle" | "signed-out" | "gone";
const END_REASONS: readonly EndReason[] = ["finished", "idle", "signed-out", "gone"];

export interface StreamState {
  readonly events: readonly LiveEvent[];
  readonly keys: ReadonlySet<string>;
  readonly cursor: string;
  readonly truncated: boolean;
  readonly dropped: number;
  readonly changedFrom: number;
  readonly ended: EndReason | null;
}

export const emptyStream: StreamState = { events: [], keys: new Set(), cursor: "", truncated: false, dropped: 0, changedFrom: 0, ended: null };

/** The new events of a batch, checked and without repeats, sorted. */
function fresh(state: StreamState, incoming: readonly unknown[]): LiveEvent[] {
  const seen = new Set<string>();
  const out: LiveEvent[] = [];
  for (const raw of incoming) {
    const e = toEvent(raw);
    if (!e) continue;
    const key = eventKey(e);
    if (state.keys.has(key) || seen.has(key)) continue;
    seen.add(key);
    out.push(e);
  }
  return out.sort(compareEvents);
}

/** Two sorted lists as one sorted list, and the index of the first event taken from `added`. */
function mergeSorted(old: readonly LiveEvent[], added: readonly LiveEvent[]): { events: LiveEvent[]; first: number } {
  const events: LiveEvent[] = [];
  let i = 0;
  let j = 0;
  let first = -1;
  while (i < old.length || j < added.length) {
    const takeAdded = i >= old.length || (j < added.length && compareEvents(added[j], old[i]) < 0);
    if (takeAdded && first < 0) first = events.length;
    events.push(takeAdded ? added[j++] : old[i++]);
  }
  return { events, first: first < 0 ? events.length : first };
}

export function mergeEvents(state: StreamState, incoming: readonly unknown[], cursor?: string): StreamState {
  const added = fresh(state, incoming);
  const nextCursor = typeof cursor === "string" ? cursor : state.cursor;
  if (added.length === 0) return { ...state, cursor: nextCursor, changedFrom: state.events.length };
  const merged = mergeSorted(state.events, added);
  const overflow = merged.events.length - MAX_EVENTS;
  const drop = overflow > 0 ? Math.ceil(overflow / DROP_BLOCK) * DROP_BLOCK : 0;
  const events = drop > 0 ? merged.events.slice(drop) : merged.events;
  const keys = new Set(drop > 0 ? events.map(eventKey) : [...state.keys, ...added.map(eventKey)]);
  return {
    events,
    keys,
    cursor: nextCursor,
    truncated: state.truncated || drop > 0,
    dropped: state.dropped + drop,
    changedFrom: Math.max(0, merged.first - drop),
    ended: state.ended,
  };
}

/** The stream ended, and why. An unknown reason reads as "idle": the page never says a run finished unless told so. */
export function endStream(state: StreamState, reason: unknown): StreamState {
  const ended = END_REASONS.includes(reason as EndReason) ? (reason as EndReason) : "idle";
  return { ...state, ended };
}
