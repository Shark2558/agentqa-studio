import { memo, type ReactNode } from "react";
import { CheckCircle, CircleDashed, HandPalm, MinusCircle, Prohibit, Spinner, WarningCircle, XCircle } from "@phosphor-icons/react";
import { cardModel, counterText, displayState, type BoardModel, type Card, type CardState } from "../../lib/live/board";

export const STATE_WORDS: Readonly<Record<CardState, string>> = {
  queued: "Queued", running: "Running", waiting: "Waiting for you", done: "Done", skipped: "Skipped", failed: "Failed",
  "not-in-run": "Not in this run", "not-reached": "Not reached", "did-not-finish": "Did not finish",
};
const ICONS: Readonly<Record<CardState, ReactNode>> = {
  queued: <CircleDashed aria-hidden="true" />, running: <Spinner aria-hidden="true" />, waiting: <HandPalm aria-hidden="true" />,
  done: <CheckCircle aria-hidden="true" />, skipped: <Prohibit aria-hidden="true" />, failed: <XCircle aria-hidden="true" />,
  "not-in-run": <MinusCircle aria-hidden="true" />, "not-reached": <CircleDashed aria-hidden="true" />,
  "did-not-finish": <WarningCircle aria-hidden="true" />,
};

export function elapsed(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

function metaText(card: Card, board: BoardModel): string {
  const until = card.endedAt ?? board.tLast;
  const time = card.startedAt !== null && until !== null ? elapsed(until - card.startedAt) : null;
  const model = cardModel(card) || (card.startedAt !== null ? "no AI" : null);
  const cost = card.cost > 0 ? `$${card.cost.toFixed(4)}` : null;
  return [time, model, cost].filter(Boolean).join(" · ");
}

type CardProps = { card: Card; state: CardState; meta: string; selected: boolean; onSelect: (agent: string) => void };

/** One agent: its state as border + glyph + word (never colour alone), its live counters, time, model and cost. It
 *  gets only what it shows, so a card whose agent did nothing new is not drawn again on each event. */
export const AgentCard = memo(function AgentCard({ card, state, meta, selected, onSelect }: CardProps) {
  const counters = counterText(card);
  const why = state === "skipped" ? card.skipWhy : state === "failed" && card.error ? `${card.error}; see the run log` : null;
  const helpers = card.helpers.length ? `with ${card.helpers.length} helper${card.helpers.length === 1 ? "" : "s"}` : null;
  return (
    <button type="button" className={`agent ${state}${selected ? " selected" : ""}`} aria-pressed={selected} onClick={() => onSelect(card.agent)}>
      <span className="name">
        {ICONS[state]}
        {card.label}
      </span>
      <span className="state">{[STATE_WORDS[state], why ?? counters, helpers].filter(Boolean).join(" · ")}</span>
      <span className="meta">{meta}</span>
    </button>
  );
});

type BoardProps = { board: BoardModel; runOver: boolean; selected: string | null; onSelect: (agent: string) => void };

export function AgentBoard({ board, runOver, selected, onSelect }: BoardProps) {
  const running = board.running ? board.cards.get(board.running) : undefined;
  return (
    <section className="card" aria-labelledby="h-agents">
      <h2 id="h-agents">Agents</h2>
      <p className="sr-only" role="status">
        {running ? `${running.label}: running` : runOver ? "The run is over" : ""}
      </p>
      <div className="agents">
        {board.order.map((agent) => {
          const card = board.cards.get(agent);
          if (!card) return null;
          return <AgentCard key={agent} card={card} state={displayState(card, board, runOver)} meta={metaText(card, board)} selected={selected === agent} onSelect={onSelect} />;
        })}
      </div>
    </section>
  );
}
