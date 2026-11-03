/** One run in the Live View: the connection (WebSocket, then SSE), the merged events, the checkpoint timeline and
 *  the replay player, giving the model at the player's position. While following live the position is simply the
 *  newest event; a finished run settles at its final picture (or this viewer's saved spot) once its stream ends. */
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import type { BoardDef } from "./board";
import { connectLive, type ConnStatus, type Transport } from "./connect";
import type { LiveEvent } from "./event";
import { buildTimeline, CHECKPOINT_EVERY, modelAt, type Model, type Timeline } from "./model";
import { dwellMs, INSTANT_STEP, loadPosition, playerReducer, savePosition, type Player, type PlayerAction } from "./player";
import { emptyStream, endStream, mergeEvents, type StreamState } from "./stream";

type StreamAction = { type: "events"; events: unknown[]; cursor?: string } | { type: "end"; reason: string; cursor?: string };

interface RunState {
  stream: StreamState;
  timeline: Timeline;
}

/** The checkpoints that still hold once `blocks` blocks of 500 were dropped from the front: the one at that boundary
 *  becomes the new start, so what the dropped events did stays in the picture. None when the drop outran them. */
function afterDrop(timeline: Timeline, blocks: number): Timeline | undefined {
  if (blocks === 0) return timeline;
  return blocks < timeline.checkpoints.length ? { checkpoints: timeline.checkpoints.slice(blocks) } : undefined;
}

function runReducer(def: BoardDef) {
  return (s: RunState, a: StreamAction): RunState => {
    if (a.type === "end") return { ...s, stream: endStream(a.cursor ? { ...s.stream, cursor: a.cursor } : s.stream, a.reason) };
    const stream = mergeEvents(s.stream, a.events, a.cursor);
    if (stream.events === s.stream.events) return { ...s, stream };
    const previous = afterDrop(s.timeline, (stream.dropped - s.stream.dropped) / CHECKPOINT_EVERY);
    return { stream, timeline: buildTimeline(stream.events, def, previous, previous ? stream.changedFrom : 0) };
  };
}

export interface LiveView {
  stream: StreamState;
  model: Model;
  pos: number;
  player: Player;
  dispatch: (a: PlayerAction) => void;
  status: ConnStatus;
  transport: Transport | null;
  runOver: boolean;
}

const FOLLOWING: Player = { pos: 0, playing: true, speed: 1, follow: true };

function useConnection(slug: string, session: string, send: (a: StreamAction) => void) {
  const [status, setStatus] = useState<ConnStatus>("connecting");
  const [transport, setTransport] = useState<Transport | null>(null);
  const cursor = useRef("");
  useEffect(
    () =>
      connectLive(slug, session, {
        cursor: () => cursor.current,
        onEvents: (events, next) => {
          if (next) cursor.current = next;
          send({ type: "events", events, cursor: next });
        },
        onEnd: (reason, next) => {
          if (next) cursor.current = next;
          send({ type: "end", reason, cursor: next });
        },
        onStatus: (s) => {
          setStatus(s);
          if (s === "signed-out" || s === "gone") send({ type: "end", reason: s });   // no retry follows these
        },
        onTransport: setTransport,
      }),
    [slug, session, send],
  );
  return { status, transport };
}

/** Replay, one event at a time, paced like the v0.8 player: the pause belongs to the event just shown. A new batch
 *  must not restart that pause (batches come every 0.5 s, a screenshot lingers 650 ms), so the step waits on the event
 *  shown and on whether there is a next one, not on the growing list; the total is read when the step fires. */
function useReplayClock(player: Player, pos: number, events: readonly LiveEvent[], dispatch: (a: PlayerAction) => void) {
  const total = events.length;
  const totalRef = useRef(total);
  useEffect(() => {
    totalRef.current = total;
  }, [total]);
  const shown = pos > 0 ? events[pos - 1] : undefined;
  const hasNext = pos < total;
  useEffect(() => {
    if (player.follow || !player.playing || !hasNext) return;
    const ms = shown ? dwellMs(shown, player.speed, 0, false) : 0;
    const id = setTimeout(() => dispatch({ type: "advance", by: player.speed === 0 ? INSTANT_STEP : 1, total: totalRef.current }), ms);
    return () => clearTimeout(id);
  }, [player, shown, hasNext, dispatch]);
}

/** A run that was over when opened settles at its final picture, or this viewer's saved spot (decision 4); a drop of
 *  the oldest events moves the position with them; the spot is saved while not following. */
function usePlacement(slug: string, session: string, stream: StreamState, player: Player, pos: number, runningAtOpen: boolean,
                      dispatch: (a: PlayerAction) => void) {
  const settled = useRef(false);
  const dropped = useRef(0);
  const total = stream.events.length;
  useEffect(() => {
    if (!stream.ended || settled.current || runningAtOpen) return;
    settled.current = true;
    dispatch({ type: "settle", total, saved: loadPosition(slug, session) });
  }, [stream.ended, runningAtOpen, slug, session, total, dispatch]);
  useEffect(() => {
    const by = stream.dropped - dropped.current;
    dropped.current = stream.dropped;
    if (by > 0) dispatch({ type: "shift", by });
  }, [stream.dropped, dispatch]);
  useEffect(() => {
    if (!player.follow) savePosition(slug, session, { ...player, pos });
  }, [player, pos, slug, session]);
}

export function useLive(slug: string, session: string, def: BoardDef, running: boolean): LiveView {
  const reducer = useMemo(() => runReducer(def), [def]);
  const [run, send] = useReducer(reducer, def, (d) => ({ stream: emptyStream, timeline: buildTimeline([], d) }));
  const [player, dispatch] = useReducer(playerReducer, FOLLOWING);
  const [runningAtOpen] = useState(running);
  const { status, transport } = useConnection(slug, session, send);
  const { stream, timeline } = run;
  const pos = player.follow ? stream.events.length : Math.min(player.pos, stream.events.length);
  useReplayClock(player, pos, stream.events, dispatch);
  usePlacement(slug, session, stream, player, pos, runningAtOpen, dispatch);
  const model = useMemo(() => modelAt(timeline, stream.events, pos, def), [timeline, stream.events, pos, def]);
  // Only a finished run is over: an hour without news, an ended sign-in or a run that is gone never claim that its
  // stages "did not finish" (TypeScript review).
  return { stream, model, pos, player, dispatch, status, transport, runOver: stream.ended === "finished" };
}
