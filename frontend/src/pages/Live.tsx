import { useEffect, useReducer, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle, CircleDashed, HandPalm, Play, Spinner, XCircle } from "@phosphor-icons/react";
import { api, type LiveEvent } from "../lib/api";
import { initialLiveState, reduceLive, type AgentState } from "../lib/live";
import { SkeletonCards } from "../components/Skeleton";

const ICONS: Record<AgentState, React.ReactNode> = {
  running: <Spinner aria-hidden="true" />,
  done: <CheckCircle aria-hidden="true" />,
  waiting: <HandPalm aria-hidden="true" />,
  idle: <CircleDashed aria-hidden="true" />,
  failed: <XCircle aria-hidden="true" />,
};
const LABELS: Record<AgentState, string> = { running: "Running", done: "Done", waiting: "Waiting for you", idle: "Queued", failed: "Failed" };
const MAX_SHOWN = 300;

/** Live View (M0.5 board + stream, M1.2-UI states): one card per agent and the event stream over Server-Sent Events.
 *  Honest states: a skeleton while the runs load, "No run yet" with the way to start one, "Waiting for the first
 *  event…" once a run is chosen, and an error when the list fails. Live View v2 (M1.3) builds the rest. */
export function Live() {
  const { slug = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const sessions = useQuery({ queryKey: ["live-sessions", slug], queryFn: () => api.liveSessions(slug) });
  const session = params.get("session") ?? sessions.data?.[0]?.id ?? "";
  const [state, dispatch] = useReducer(reduceLive, initialLiveState);
  // The states the cards had when they first appeared: a tick draws itself only on a card that changed afterwards,
  // so a replayed run shows its final board quietly instead of animating every card at once.
  const [baseline, setBaseline] = useState<Map<string, AgentState> | null>(null);

  useEffect(() => {
    dispatch({ type: "reset" });                       // another run: start the board from nothing
    setBaseline(null);
    if (!session) return;
    const source = new EventSource(api.streamUrl(slug, session));
    source.addEventListener("live", (e) => {
      try {
        const payload = JSON.parse((e as MessageEvent<string>).data) as { events: LiveEvent[] };
        dispatch({ type: "events", events: payload.events });
      } catch {
        // A truncated frame is skipped; the next batch carries on from the server's cursor.
      }
    });
    source.addEventListener("end", () => {
      dispatch({ type: "end" });
      source.close();
    });
    return () => source.close();
  }, [slug, session]);

  useEffect(() => {
    if (baseline === null && state.agents.length > 0) setBaseline(new Map(state.agents.map((a) => [a.agent, a.state])));
  }, [baseline, state.agents]);

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
          <p className="sub">
            {session ? <span className="mono">{session}</span> : "No run yet"}
            {state.ended && <span className="pill neutral">finished</span>}
          </p>
        </div>
        <div className="spacer" />
        {sessions.data && sessions.data.length > 0 && (
          <>
            <label htmlFor="session" className="small muted">
              Run
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

      <div className="grid g-live">
        <section className="card" aria-labelledby="h-agents" aria-busy={sessions.isPending || undefined}>
          <h2 id="h-agents">Agents</h2>
          {sessions.isPending && <SkeletonCards />}
          {noRun && (
            <div className="empty">
              <p>No run yet. Start one from the project page and watch the agents work here.</p>
              <Link className="btn primary" to={projectHref}>
                <Play aria-hidden="true" />
                Go to the project page
              </Link>
            </div>
          )}
          {session && state.agents.length === 0 && <p className="muted">Waiting for the first event…</p>}
          <div className="agents one-col">
            {state.agents.map((a) => {
              const changed = baseline !== null && baseline.get(a.agent) !== a.state;
              return (
                <div key={a.agent} className={`agent ${a.state}${changed ? " changed" : ""}`}>
                  <div className="name">
                    {ICONS[a.state]}
                    {a.agent}
                  </div>
                  <div className="state">
                    {LABELS[a.state]} · {a.last}
                  </div>
                  <div className="meta">{a.steps} events</div>
                </div>
              );
            })}
          </div>
        </section>
        <section className="card flat" aria-labelledby="h-stream">
          <h2 id="h-stream">What is happening</h2>
          {!session && !sessions.isPending && <p className="muted">Nothing to show until a run starts.</p>}
          <div className="stream" tabIndex={0} aria-label="Live events" aria-live="polite">
            {state.events.slice(-MAX_SHOWN).map((e) => (
              <div key={`${e.w}-${e.seq}-${e.t}`} className={`evt ${e.level === "bad" ? "fail" : ""}`}>
                <div className="k">{e.agent}</div>
                <div>
                  <p>{e.title}</p>
                  <div className="t">
                    {new Date(e.t * 1000).toLocaleTimeString()} · {e.kind}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
