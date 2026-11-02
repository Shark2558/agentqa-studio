import { useEffect, useReducer } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle, CircleDashed, HandPalm, Spinner, XCircle } from "@phosphor-icons/react";
import { api, type LiveEvent } from "../lib/api";
import { initialLiveState, reduceLive, type AgentState } from "../lib/live";

const ICONS: Record<AgentState, React.ReactNode> = {
  running: <Spinner aria-hidden="true" />,
  done: <CheckCircle aria-hidden="true" />,
  waiting: <HandPalm aria-hidden="true" />,
  idle: <CircleDashed aria-hidden="true" />,
  failed: <XCircle aria-hidden="true" />,
};
const LABELS: Record<AgentState, string> = { running: "Running", done: "Done", waiting: "Waiting for you", idle: "Queued", failed: "Failed" };
const MAX_SHOWN = 300;

/** Live View (bare, M0.5): one card per agent and the event stream over Server-Sent Events. M1.3 builds it out. */
export function Live() {
  const { slug = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const sessions = useQuery({ queryKey: ["live-sessions", slug], queryFn: () => api.liveSessions(slug) });
  const session = params.get("session") ?? sessions.data?.[0]?.id ?? "";
  const [state, dispatch] = useReducer(reduceLive, initialLiveState);

  useEffect(() => {
    dispatch({ type: "reset" });                       // another run: start the board from nothing
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

  return (
    <>
      <div className="topbar">
        <div>
          <div className="crumbs">
            <Link to="/">Projects</Link> / <Link to={`/projects/${encodeURIComponent(slug)}`}>{slug}</Link> / <b>Live View</b>
          </div>
          <h1>Live View</h1>
          <p className="sub">
            {session ? <span className="mono">{session}</span> : "No run yet"}
            {state.ended && <span className="pill neutral">finished</span>}
          </p>
        </div>
        <div className="spacer" />
        <label htmlFor="session" className="small muted">
          Run
        </label>
        <select id="session" value={session} onChange={(e) => setParams({ session: e.target.value })}>
          {sessions.data?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
              {s.running ? " · running" : ""}
            </option>
          ))}
        </select>
      </div>

      <div className="grid g-live">
        <section className="card" aria-labelledby="h-agents">
          <h2 id="h-agents">Agents</h2>
          {state.agents.length === 0 && <p className="muted">Waiting for the first event…</p>}
          <div className="agents one-col">
            {state.agents.map((a) => (
              <div key={a.agent} className={`agent ${a.state}`}>
                <div className="name">
                  {ICONS[a.state]}
                  {a.agent}
                </div>
                <div className="state">
                  {LABELS[a.state]} · {a.last}
                </div>
                <div className="meta">{a.steps} events</div>
              </div>
            ))}
          </div>
        </section>
        <section className="card flat" aria-labelledby="h-stream">
          <h2 id="h-stream">What is happening</h2>
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
