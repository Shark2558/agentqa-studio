import { memo } from "react";
import { CheckCircle, CircleDashed, HandPalm, Spinner, XCircle } from "@phosphor-icons/react";
import type { AgentCard as Card, AgentState } from "../../lib/live";

const ICONS: Record<AgentState, React.ReactNode> = {
  running: <Spinner aria-hidden="true" />,
  done: <CheckCircle aria-hidden="true" />,
  waiting: <HandPalm aria-hidden="true" />,
  idle: <CircleDashed aria-hidden="true" />,
  failed: <XCircle aria-hidden="true" />,
};
export const STATE_LABELS: Record<AgentState, string> = { running: "Running", done: "Done", waiting: "Waiting for you", idle: "Queued", failed: "Failed" };

/** One agent: its state as border + glyph + word, pulsing while running, drawing its tick only when it changed live. */
export const AgentCard = memo(function AgentCard({ card }: { card: Card }) {
  return (
    <div className={`agent ${card.state}${card.changed ? " changed" : ""}`}>
      <div className="name">
        {ICONS[card.state]}
        {card.agent}
      </div>
      <div className="state">
        {STATE_LABELS[card.state]} · {card.last}
      </div>
      <div className="meta">{card.steps} events</div>
    </div>
  );
});
