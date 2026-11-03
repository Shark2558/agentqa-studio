/** The live page's state: events in order, one card per agent, derived purely from the stream. Every event is
 *  counted once (a reconnect may replay), and a card is "changed" only when its state moved after the first batch,
 *  so history draws quietly and only live changes animate. */
import type { LiveEvent } from "./api";

export type AgentState = "running" | "done" | "waiting" | "idle" | "failed";

export interface AgentCard {
  agent: string;
  state: AgentState;
  last: string;
  steps: number;
  changed: boolean;
}

export interface LiveState {
  events: LiveEvent[];
  agents: AgentCard[];
  ended: boolean;
  seen: ReadonlySet<string>;
  batches: number;
  cursor: string;
  lastChange: { agent: string; state: AgentState } | null;
}

export const initialLiveState: LiveState = { events: [], agents: [], ended: false, seen: new Set(), batches: 0, cursor: "", lastChange: null };
const MAX_EVENTS = 2000;
const MAX_SEEN = 5000;

function stateFor(kind: string, level: string | undefined, previous: AgentState): AgentState {
  if (kind === "stage_start") return "running";
  if (kind === "stage_end") return level === "bad" ? "failed" : "done";
  if (kind === "assist") return "waiting";
  return previous === "idle" ? "running" : previous;
}

export type LiveAction = { type: "events"; events: LiveEvent[]; cursor?: string } | { type: "end" } | { type: "reset" };

const keyOf = (e: LiveEvent) => `${e.w}:${e.seq}`;

/** The events of a batch that have not been seen before, and the seen-set after them. */
function unseen(state: LiveState, events: LiveEvent[]): { fresh: LiveEvent[]; seen: Set<string> } {
  const seen = new Set(state.seen.size > MAX_SEEN ? state.events.map(keyOf) : state.seen);
  const fresh: LiveEvent[] = [];
  for (const e of events) {
    const key = keyOf(e);
    if (seen.has(key)) continue;
    seen.add(key);
    fresh.push(e);
  }
  return { fresh, seen };
}

export function reduceLive(state: LiveState, action: LiveAction): LiveState {
  if (action.type === "reset") return initialLiveState;
  if (action.type === "end") return { ...state, ended: true };
  const { fresh, seen } = unseen(state, action.events);
  const live = state.batches > 0;
  const cards = new Map(state.agents.map((a) => [a.agent, a]));
  let lastChange = state.lastChange;
  for (const e of fresh) {
    const card = cards.get(e.agent) ?? { agent: e.agent, state: "idle" as AgentState, last: "", steps: 0, changed: false };
    const next = stateFor(e.kind, e.level, card.state);
    const moved = live && cards.has(e.agent) && next !== card.state;
    if (moved) lastChange = { agent: e.agent, state: next };
    cards.set(e.agent, { ...card, state: next, last: e.title, steps: card.steps + 1, changed: card.changed || moved });
  }
  return {
    events: [...state.events, ...fresh].slice(-MAX_EVENTS),
    agents: [...cards.values()],
    ended: state.ended,
    seen,
    batches: state.batches + 1,
    cursor: action.cursor ?? state.cursor,
    lastChange,
  };
}
