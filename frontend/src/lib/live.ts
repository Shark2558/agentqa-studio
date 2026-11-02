/** The live page's state: events in order, one card per agent, derived purely from the stream. */
import type { LiveEvent } from "./api";

export type AgentState = "running" | "done" | "waiting" | "idle" | "failed";

export interface AgentCard {
  agent: string;
  state: AgentState;
  last: string;
  steps: number;
}

export interface LiveState {
  events: LiveEvent[];
  agents: AgentCard[];
  ended: boolean;
}

export const initialLiveState: LiveState = { events: [], agents: [], ended: false };
const MAX_EVENTS = 2000;

function stateFor(kind: string, level: string | undefined, previous: AgentState): AgentState {
  if (kind === "stage_start") return "running";
  if (kind === "stage_end") return level === "bad" ? "failed" : "done";
  if (kind === "assist") return "waiting";
  return previous === "idle" ? "running" : previous;
}

export type LiveAction = { type: "events"; events: LiveEvent[] } | { type: "end" } | { type: "reset" };

export function reduceLive(state: LiveState, action: LiveAction): LiveState {
  if (action.type === "reset") return initialLiveState;
  if (action.type === "end") return { ...state, ended: true };
  const cards = new Map(state.agents.map((a) => [a.agent, a]));
  for (const e of action.events) {
    const card = cards.get(e.agent) ?? { agent: e.agent, state: "idle" as AgentState, last: "", steps: 0 };
    cards.set(e.agent, {
      ...card,
      state: stateFor(e.kind, e.level, card.state),
      last: e.title,
      steps: card.steps + 1,
    });
  }
  const events = [...state.events, ...action.events].slice(-MAX_EVENTS);
  return { events, agents: [...cards.values()], ended: state.ended };
}
