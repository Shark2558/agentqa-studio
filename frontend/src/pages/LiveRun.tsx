import { useCallback, useEffect, useRef } from "react";
import { useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useMe } from "../App";
import { canWrite } from "../lib/can";
import { useAssist } from "../lib/useAssist";
import { NeedsYouBanner } from "../components/assist/NeedsYouBanner";
import { PauseButton } from "../components/assist/PauseButton";
import type { BoardDef } from "../lib/live/board";
import type { ConnStatus } from "../lib/live/connect";
import type { StreamState } from "../lib/live/stream";
import { useLive } from "../lib/live/useLive";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { AgentBoard } from "../components/live/AgentBoard";
import { AgentFocus } from "../components/live/AgentFocus";
import { DetailsTabs, TABS, type Tab } from "../components/live/DetailsTabs";
import { PipelineCard, RunHeader } from "../components/live/LiveHeader";
import { useGateCounts } from "../lib/useGateCounts";
import { PlayerBar } from "../components/live/PlayerBar";
import { Findings, TestTiles } from "../components/live/TestsAndFindings";

type NoticeProps = { stream: StreamState; status: ConnStatus; skipped: number; onReconnect: () => void };

/** What the page must say plainly: a run that is gone, a sign-in that ended, an hour without news, a lost
 *  connection, a run too long to keep whole, events it could not show. */
function RunNotices({ stream, status, skipped, onReconnect }: NoticeProps) {
  const again = <button type="button" className="btn sm" onClick={onReconnect}>Check again</button>;
  return (
    <>
      {stream.ended === "gone" && <p className="notice warn" role="alert">This run no longer exists.</p>}
      {stream.ended === "signed-out" && <p className="notice warn" role="alert">Your sign-in ended: sign in again to keep watching.</p>}
      {stream.ended === "idle" && <p className="notice warn row" role="status">No news from this run for an hour: it may be waiting for you, or it stopped. {again}</p>}
      {status === "lost" && <p className="notice warn row" role="alert">The connection to the server was lost. {again}</p>}
      {stream.truncated && (
        <p className="notice warn" role="status">This run is very long: the replay keeps its newest 50 000 events; the totals still count every event.</p>
      )}
      {skipped > 0 && <p className="notice warn" role="status">{skipped} event{skipped === 1 ? "" : "s"} could not be shown and {skipped === 1 ? "was" : "were"} skipped.</p>}
    </>
  );
}

const NARROW = "(max-width: 1023px)";

/** Under 1 024 px the focus column sits below the board: choosing an agent brings it into sight (M1.3 C13). */
function showFocus() {
  if (typeof window.matchMedia !== "function" || !window.matchMedia(NARROW).matches) return;
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.getElementById("h-focus")?.closest("section")?.scrollIntoView?.({ block: "start", behavior: still ? "auto" : "smooth" });
}

/** A new question in the recording (the board's open assists grew) asks for the help box's list at once, instead of
 *  waiting for its next poll. */
function useAskWhenAgentsWait(slug: string, waiting: number) {
  const queryClient = useQueryClient();
  const before = useRef(waiting);
  useEffect(() => {
    if (waiting > before.current) queryClient.invalidateQueries({ queryKey: ["assist", slug] });
    before.current = waiting;
  }, [waiting, slug, queryClient]);
}

/** `newest`: the run shown is the project's newest, so its gates may say what is still open now (an older run's have moved on). */
type Props = { slug: string; session: string; def: BoardDef; running: boolean; newest: boolean; onReconnect: () => void };

/** One run in the Live View (M1.3): header, pipeline, board, what the chosen agent is doing, tests and findings,
 *  details and replay. The chosen agent and tab live in the address, so a link shows the same view; an agent the board
 *  does not know falls back to the one running. A broken part is tried again when the replay moves on. */
export function LiveRun({ slug, session, def, running, newest, onReconnect }: Props) {
  const [params, setParams] = useSearchParams();
  const view = useLive(slug, session, def, running);
  const gates = useGateCounts(newest ? slug : null);
  const now = newest ? gates.data ?? null : null;
  const { model, stream, pos, shownOver } = view;
  const requested = params.get("agent");
  const agent = requested && model.board.cards.has(requested) ? requested : model.board.running;
  const tabParam = params.get("tab");
  const tab: Tab = TABS.includes(tabParam as Tab) ? (tabParam as Tab) : "document";
  const set = useCallback((key: string, value: string) => setParams((p) => {
    const next = new URLSearchParams(p);
    next.set(key, value);
    return next;
  }, { replace: true }), [setParams]);
  const select = useCallback((a: string) => {
    set("agent", a);
    showFocus();
  }, [set]);
  const mayDrive = canWrite(useMe().data?.role);
  const paused = useAssist(slug).data?.paused;
  useAskWhenAgentsWait(slug, model.board.assists.size);
  const labels = (a: string) => model.board.cards.get(a)?.label ?? (Object.hasOwn(def.labels, a) ? def.labels[a] : a);
  const jumpTo = (a: string) => {
    const i = stream.events.findIndex((e) => e.agent === a && e.kind === "stage_start");
    select(a);
    if (i >= 0) view.dispatch({ type: "scrub", pos: i + 1, total: stream.events.length });
  };
  return (
    <>
      <div className="run-head">
        <ErrorBoundary><RunHeader model={model} status={view.status} ended={stream.ended} transport={view.transport} /></ErrorBoundary>
        {mayDrive && newest && <PauseButton slug={slug} paused={paused} running={running} />}
      </div>
      <NeedsYouBanner slug={slug} />
      <RunNotices stream={stream} status={view.status} skipped={model.skipped} onReconnect={onReconnect} />
      <ErrorBoundary resetKey={pos}><PipelineCard model={model} def={def} runOver={shownOver} slug={slug} now={now} onJump={jumpTo} /></ErrorBoundary>
      <ErrorBoundary><PlayerBar player={view.player} pos={pos} total={stream.events.length} ended={stream.ended} dispatch={view.dispatch} /></ErrorBoundary>
      <div className="grid g-live mt-4">
        <ErrorBoundary resetKey={pos}><AgentBoard board={model.board} runOver={shownOver} selected={agent} onSelect={select} /></ErrorBoundary>
        <ErrorBoundary resetKey={pos}>
          <AgentFocus key={agent ?? "all"} slug={slug} session={session} model={model} events={stream.events} pos={pos} agent={agent} runOver={shownOver} />
        </ErrorBoundary>
        <div className="stack">
          <ErrorBoundary resetKey={pos}><TestTiles panels={model.panels} runOver={shownOver} /></ErrorBoundary>
          <ErrorBoundary resetKey={pos}><Findings panels={model.panels} /></ErrorBoundary>
        </div>
      </div>
      <ErrorBoundary resetKey={pos}>
        <DetailsTabs model={model} events={stream.events} pos={pos} tab={tab} onTab={(t) => set("tab", t)} labels={labels} />
      </ErrorBoundary>
    </>
  );
}
