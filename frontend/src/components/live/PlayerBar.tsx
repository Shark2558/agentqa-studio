import { useId } from "react";
import { Pause, Play, SkipBack, SkipForward, Broadcast } from "@phosphor-icons/react";
import { SPEEDS, type Player, type PlayerAction, type Speed } from "../../lib/live/player";

type Props = { player: Player; pos: number; total: number; runOver: boolean; dispatch: (a: PlayerAction) => void };

/** What a screen reader hears: the player's state when it changes, never the position on every event. */
function stateWords(player: Player, pos: number, total: number, runOver: boolean): string {
  if (player.follow && !runOver) return "Following the run live";
  if (runOver && pos >= total && !player.playing) return "Final picture";
  return player.playing ? "Playing" : "Paused";
}

/** Replay: from the start, play / pause, one step, speed, a position slider and Go live (back to the newest event). */
export function PlayerBar({ player, pos, total, runOver, dispatch }: Props) {
  const id = useId();
  const live = player.follow && !runOver;
  const playing = player.playing && !player.follow;
  return (
    <section className="card player" aria-label="Replay">
      <button type="button" className="btn" onClick={() => dispatch({ type: "restart" })}>
        <SkipBack aria-hidden="true" />
        Replay from the start
      </button>
      <button type="button" className="btn" onClick={() => dispatch({ type: "toggle" })} aria-label={playing ? "Pause" : "Play"} disabled={player.follow}>
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
      <span className="sr-only" role="status">{stateWords(player, pos, total, runOver)}</span>
      <button type="button" className="btn" onClick={() => dispatch({ type: "live", total })} disabled={live}>
        <Broadcast aria-hidden="true" />
        {runOver ? "Final picture" : "Go live"}
      </button>
    </section>
  );
}
