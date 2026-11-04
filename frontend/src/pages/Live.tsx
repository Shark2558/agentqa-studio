import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Play } from "@phosphor-icons/react";
import { useMe } from "../App";
import { api, type LiveSession } from "../lib/api";
import { canWrite } from "../lib/can";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { SkeletonCards } from "../components/Skeleton";
import { LiveRun } from "./LiveRun";

const WAIT_POLL_MS = 3_000;            // a run named in the address but not listed yet: look again for about a minute
const WAIT_POLLS = 20;
const RUNNING_POLL_MS = 15_000;        // while a run is going, so the list notices when it ends

/** The run to show: the one in the address when it is listed (nothing while it is not, never another run), else the
 *  one running, else the newest with events. */
export function chooseSession(requested: string | null, listed: readonly LiveSession[] | undefined): string {
  if (!listed) return "";
  if (requested) return listed.some((s) => s.id === requested) ? requested : "";
  return (listed.find((s) => s.running) ?? listed.find((s) => s.has_events) ?? listed[0])?.id ?? "";
}

type PickerProps = { sessions: readonly LiveSession[]; session: string; onPick: (id: string) => void };

function RunPicker({ sessions, session, onPick }: PickerProps) {
  return (
    <>
      <label htmlFor="session" className="small muted">Run to watch</label>
      <select id="session" value={session} onChange={(e) => onPick(e.target.value)}>
        {!session && <option value="" disabled>Pick a run</option>}
        {sessions.map((s) => (
          <option key={s.id} value={s.id}>
            {s.label} · {s.when}
            {s.running ? " · running" : ""}
          </option>
        ))}
      </select>
    </>
  );
}

function NoRun({ mayRun, projectHref }: { mayRun: boolean; projectHref: string }) {
  return (
    <div className="empty card">
      <p>No run yet.{mayRun ? " Start one from the project page and watch the agents work here." : ""}</p>
      {mayRun && (
        <Link className="btn primary" to={projectHref}>
          <Play aria-hidden="true" />
          Go to the project page
        </Link>
      )}
    </div>
  );
}

/** Live View v2 (M1.3): pick a run (the address keeps it), load the board, then watch or replay it. Honest states: a
 *  skeleton while the runs load, "No run yet" with the way to start one (only for someone who may start runs), a
 *  notice while a run named in the address is not listed yet, and an alert when the list or the board cannot load. */
export function Live() {
  const { slug = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const requested = params.get("session");
  const [attempt, setAttempt] = useState(0);
  const mayRun = canWrite(useMe().data?.role);
  const sessions = useQuery({
    queryKey: ["live-sessions", slug], queryFn: () => api.liveSessions(slug),
    refetchInterval: (q) => (requested && !q.state.data?.some((s) => s.id === requested) && q.state.dataUpdateCount < WAIT_POLLS
      ? WAIT_POLL_MS : q.state.data?.some((s) => s.running) ? RUNNING_POLL_MS : false),
  });
  const board = useQuery({ queryKey: ["live-board", slug], queryFn: () => api.liveBoard(slug) });
  const session = chooseSession(requested, sessions.data);
  const chosen = sessions.data?.find((s) => s.id === session);
  const noRun = sessions.isSuccess && sessions.data.length === 0;
  const projectHref = `/projects/${encodeURIComponent(slug)}`;
  return (
    <>
      <div className="topbar">
        <div>
          <div className="crumbs"><Link to="/">Projects</Link> / <Link to={projectHref}>{slug}</Link> / <b>Live View</b></div>
          <h1>Live View</h1>
          <p className="sub">{noRun ? "No run yet" : chosen ? chosen.label : null}</p>
        </div>
        <div className="spacer" />
        {!!sessions.data?.length && <RunPicker sessions={sessions.data} session={session} onPick={(id) => setParams({ session: id })} />}
      </div>
      {(sessions.isError || board.isError) && <p className="notice bad" role="alert">The runs could not be loaded. Reload the page, or check that the server is still up.</p>}
      {(sessions.isPending || (!!chosen && board.isPending)) && <section className="card" aria-busy="true" aria-label="Loading the run"><SkeletonCards /></section>}
      {noRun && <NoRun mayRun={mayRun} projectHref={projectHref} />}
      {sessions.isSuccess && !noRun && requested && !chosen && (
        <p className="notice warn" role="status">That run is not in the list yet: it may still be starting (this page looks again for a minute), or it was removed. Pick a run above.</p>
      )}
      {chosen && board.data && sessions.isFetchedAfterMount && (
        <ErrorBoundary resetKey={`${session}/${attempt}`} message="This run could not be shown. Reloading the page usually helps.">
          <LiveRun key={`${slug}/${session}/${attempt}`} slug={slug} session={session} def={board.data} running={chosen.running}
                   newest={sessions.data?.[0]?.id === session} onReconnect={() => setAttempt((n) => n + 1)} />
        </ErrorBoundary>
      )}
    </>
  );
}
