import { Link, useParams, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Play } from "@phosphor-icons/react";
import { api, type LiveSession } from "../lib/api";
import { useLiveStream } from "../lib/liveStream";
import { SkeletonCards } from "../components/Skeleton";
import { AgentCard, STATE_LABELS } from "../components/live/AgentCard";
import { EventRow } from "../components/live/EventRow";

const MAX_SHOWN = 300;

/** The run to stream: the one in the URL when it is listed (or not yet checkable), else the newest listed one. */
function chooseSession(requested: string | null, listed: LiveSession[] | undefined): string {
  if (!listed) return requested ?? "";
  if (requested && listed.some((s) => s.id === requested)) return requested;
  return listed[0]?.id ?? "";
}

/** Live View (M0.5 board + stream, M1.2-UI states): one card per agent and the event stream over Server-Sent Events.
 *  Honest states: a skeleton while the runs load, "No run yet" with the way to start one, "Waiting for the first
 *  event…" once a run is chosen, a notice while a dropped connection is retried, an alert when the list fails.
 *  Live View v2 (M1.3) builds the rest. */
export function Live() {
  const { slug = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const sessions = useQuery({ queryKey: ["live-sessions", slug], queryFn: () => api.liveSessions(slug) });
  const session = chooseSession(params.get("session"), sessions.data);
  const noRun = sessions.isSuccess && sessions.data.length === 0;
  const projectHref = `/projects/${encodeURIComponent(slug)}`;

  return (
    <>
      <div className="topbar">
        <div>
          <div className="crumbs">
            <Link to="/">Projects</Link> / <Link to={projectHref}>{slug}</Link> / <b>Live View</b>
          </div>
          <h1>Live View</h1>
          <p className="sub">{noRun ? "No run yet" : session && <span className="mono">{session}</span>}</p>
        </div>
        <div className="spacer" />
        {sessions.data && sessions.data.length > 0 && (
          <>
            <label htmlFor="session" className="small muted">
              Run to watch
            </label>
            <select id="session" value={session} onChange={(e) => setParams({ session: e.target.value })}>
              {sessions.data.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                  {s.running ? " · running" : ""}
                </option>
              ))}
            </select>
          </>
        )}
      </div>
      {sessions.isError && (
        <p className="notice bad" role="alert">
          The runs could not be loaded. Reload the page, or check that the server is still up.
        </p>
      )}
      <LiveRun key={`${slug}/${session}`} slug={slug} session={session} isPending={sessions.isPending} noRun={noRun} projectHref={projectHref} />
    </>
  );
}

type RunProps = { slug: string; session: string; isPending: boolean; noRun: boolean; projectHref: string };

/** The board and the stream for one run; keyed by the run, so another run starts from nothing. */
function LiveRun({ slug, session, isPending, noRun, projectHref }: RunProps) {
  const { state, status } = useLiveStream(slug, session);
  const waiting = session && state.agents.length === 0 && status !== "ended";
  const endedEmpty = status === "ended" && state.events.length === 0;
  const announcement = isPending ? "Loading runs…" : state.lastChange ? `${state.lastChange.agent}: ${STATE_LABELS[state.lastChange.state]}` : "";

  return (
    <>
      <p className="sr-only" role="status">
        {announcement}
      </p>
      {status === "retrying" && (
        <p className="notice warn" role="alert">
          Connection lost, retrying… Events already shown stay; new ones continue when the server answers again.
        </p>
      )}
      <div className="grid g-live">
        <section className="card" aria-labelledby="h-agents" aria-busy={isPending || undefined}>
          <h2 id="h-agents">Agents</h2>
          {isPending && <SkeletonCards />}
          {noRun && (
            <div className="empty">
              <p>No run yet. Start one from the project page and watch the agents work here.</p>
              <Link className="btn primary" to={projectHref}>
                <Play aria-hidden="true" />
                Go to the project page
              </Link>
            </div>
          )}
          {waiting && <p className="muted">Waiting for the first event…</p>}
          {endedEmpty && <p className="muted">This run ended without any event.</p>}
          <div className="agents one-col">
            {state.agents.map((a) => (
              <AgentCard key={a.agent} card={a} />
            ))}
          </div>
        </section>
        <section className="card" aria-labelledby="h-stream">
          <h2 id="h-stream">
            What is happening {state.ended && <span className="pill neutral">finished</span>}
          </h2>
          {!session && !isPending && <p className="muted">Nothing to show until a run starts.</p>}
          {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scrolling log must be reachable by keyboard */}
          <div className="stream" role="log" aria-live="off" aria-label="Live events" tabIndex={0}>
            {state.events.slice(-MAX_SHOWN).map((e) => (
              <EventRow key={`${e.w}-${e.seq}`} event={e} />
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
