import { useId } from "react";
import { Pause, Play, SkipBack, SkipForward, Broadcast } from "@phosphor-icons/react";
import { SPEEDS, type Player, type PlayerAction, type Speed } from "../../lib/live/player";
import type { EndReason } from "../../lib/live/stream";

type Props = { player: Player; pos: number; total: number; ended: EndReason | null; dispatch: (a: PlayerAction) => void };

/** What a screen reader hears: the player's state when it changes, never the position on every event. */
function stateWords(player: Player, ended: EndReason | null, atEnd: boolean): string {
  if (atEnd) return ended === "finished" ? "Final picture" : "End of what was recorded";   // nothing is left to play
  if (player.follow) return "Following the run live";
  return player.playing ? "Playing" : "Paused";
}

/** Replay: from the start, play / pause, one step, speed, a position slider and Go live (back to the newest event).
 *  At the end of a recording that can grow no more, Play starts it again from the beginning, so the button is never
 *  disabled under a keyboard user's focus (M1.3 Phase C). */
export function PlayerBar({ player, pos, total, ended, dispatch }: Props) {
  const id = useId();
  const runOver = ended === "finished";
  const live = player.follow && !runOver;
  const atEnd = ended !== null && pos >= total;                 // for a finished run, useLive's `shownOver`
  const playing = player.playing && !player.follow && !atEnd;
  const playLabel = atEnd ? "Play from the start" : playing ? "Pause" : "Play";
  return (
    <section className="card player" aria-label="Replay">
      <button type="button" className="btn" onClick={() => dispatch({ type: "restart" })}>
        <SkipBack aria-hidden="true" />
        Replay from the start
      </button>
      <button type="button" className="btn" onClick={() => dispatch({ type: atEnd ? "restart" : "toggle" })} aria-label={playLabel}
              disabled={player.follow && !atEnd}>
        {playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
      </button>
      <button type="button" className="btn" onClick={() => dispatch({ type: "step", total })} aria-label="Next step" disabled={pos >= total}>
        <SkipForward aria-hidden="true" />
      </button>
      <label htmlFor={`${id}-speed`} className="small">Speed</label>
      <select id={`${id}-speed`} value={player.speed} onChange={(e) => dispatch({ type: "speed", speed: Number(e.target.value) as Speed })}>
        {SPEEDS.map((s) => <option key={s} value={s}>{s === 0 ? "instant" : `${s}×`}</option>)}
      </select>
      <label htmlFor={`${id}-pos`} className="sr-only">Position in the run</label>
      <input id={`${id}-pos`} type="range" min={0} max={total} value={pos} aria-valuetext={`event ${pos} of ${total}`}
             onChange={(e) => dispatch({ type: "scrub", pos: Number(e.target.value), total })} />
      <span className="small mono pos">{pos} / {total}{playing ? " · playing" : ""}</span>
      <span className="sr-only" role="status">{stateWords(player, ended, atEnd)}</span>
      <button type="button" className="btn" onClick={() => dispatch({ type: "live", total })} disabled={live}>
        <Broadcast aria-hidden="true" />
        {runOver ? "Final picture" : "Go live"}
      </button>
    </section>
  );
}
