import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks, Play, Pulse, Robot } from "@phosphor-icons/react";
import { useMe } from "../App";
import { ApiError, api } from "../lib/api";
import { MODES, aiApi, capState, settingsFrom } from "../lib/ai";
import { canWrite } from "../lib/can";
import { GateCounts } from "../components/gates/GateCounts";

const RUNNING_POLL_MS = 3000;

export function Project() {
  const { slug = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const project = useQuery({ queryKey: ["project", slug], queryFn: () => api.project(slug) });
  const runs = useQuery({
    queryKey: ["runs", slug],
    queryFn: () => api.runs(slug),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "running") ? RUNNING_POLL_MS : false),
  });
  // The gates are answered in this app (M1.4), so a run waits at the plan gate unless the owner ticks the demo switch,
  // which only approves the test plan; the server writes its use in the change log (decision 3).
  const [autoApprove, setAutoApprove] = useState(false);
  const start = useMutation({
    mutationFn: () => api.startRun(slug, { scope: "pipeline", policy: "srs_wins", auto_approve: autoApprove }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["runs", slug] });
      queryClient.invalidateQueries({ queryKey: ["live-sessions", slug] });     // the Live View must not show the last run's list
      navigate(`/projects/${encodeURIComponent(slug)}/live?session=${encodeURIComponent(`job-${run.id}-${run.stage}`)}`);
    },
  });
  const ai = useQuery({ queryKey: ["ai", "project", slug], queryFn: () => aiApi.project(slug) });
  // A Viewer watches and reads; only someone who may change things is offered the Run button (the server refuses too).
  const mayRun = canWrite(useMe().data?.role);
  const running = runs.data?.find((r) => r.status === "running");
  const aiMode = ai.data ? settingsFrom(ai.data.settings).mode : null;
  const aiTitle = aiMode ? MODES.find((m) => m.id === aiMode)?.title ?? "No AI" : null;
  const aiLine = ai.data ? (aiMode === "none" || aiMode === "local" ? "nothing is spent" : capState(ai.data.budget).text) : ai.isError ? "could not be loaded" : "loading…";
  const error = start.error instanceof ApiError ? start.error : null;

  if (project.isError) return <p className="notice bad page-pad" role="alert">That project does not exist.</p>;
  if (!project.data) return <p className="muted page-pad" role="status">Loading…</p>;
  const p = project.data;

  return (
    <>
      <div className="topbar">
        <div>
          <div className="crumbs">
            <Link to="/">Projects</Link> / <b>{p.name}</b>
          </div>
          <h1>{p.name}</h1>
          <p className="sub mono">{p.url}</p>
        </div>
        <div className="spacer" />
        {mayRun && (
          <label className="check small">
            <input type="checkbox" checked={autoApprove} onChange={(e) => setAutoApprove(e.target.checked)} aria-describedby="auto-hint" />
            Approve the test plan automatically (demos)
          </label>
        )}
        <Link className="btn" to={`/projects/${encodeURIComponent(slug)}/requirements`}>
          <ListChecks aria-hidden="true" />
          Requirements
        </Link>
        <Link className="btn" to={`/projects/${encodeURIComponent(slug)}/live`}>
          <Pulse aria-hidden="true" />
          Live View
        </Link>
        {mayRun && (
          <button className="btn primary" type="button" onClick={() => start.mutate()} disabled={start.isPending || !!running}>
            <Play aria-hidden="true" />
            {running ? "Running…" : "Run full pipeline"}
          </button>
        )}
      </div>
      {mayRun && (
        <p id="auto-hint" className="small muted">
          Leave “Approve the test plan automatically” off to review the plan yourself. When ticked, the run only approves the
          test plan (every proposed case and the ready imported cases), never questions or defects, and the change log records it.
        </p>
      )}
      {error && (
        <p className="notice bad" role="alert">
          {error.message}
        </p>
      )}

      <GateCounts slug={slug} />

      <div className="grid g-dash mt-4">
        <div className="card kpi">
          <div className="label">Readiness</div>
          <div className="value">{p.score ?? "—"}</div>
          <div className="muted small">{p.verdict ?? "no finished run yet"}</div>
        </div>
        <div className="card kpi">
          <div className="label">Test cases</div>
          <div className="value">{p.cases ?? 0}</div>
        </div>
        <div className="card kpi">
          <div className="label">Open defects</div>
          <div className="value">{p.defects ?? 0}</div>
        </div>
        <div className="card kpi">
          <div className="label">Last run</div>
          <div className="value small-value">{p.last ?? "—"}</div>
        </div>
        <Link className="card kpi kpi-link" to={`/projects/${encodeURIComponent(slug)}/ai`} aria-label={aiTitle ? `AI: ${aiTitle}; ${aiLine}. Open the AI settings` : "AI settings"}>
          <div className="label">
            <Robot aria-hidden="true" /> AI
          </div>
          <div className="value small-value">{aiTitle ?? "…"}</div>
          <div className="muted small">{aiLine}</div>
        </Link>
      </div>

      <section className="card flat mt-4" aria-labelledby="h-runs">
        <h2 id="h-runs">Runs</h2>
        {runs.data?.length === 0 && <p className="muted">{mayRun ? "Nothing has run yet. Press “Run full pipeline” to start; the demo takes about six minutes." : "Nothing has run yet."}</p>}
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Stage</th>
                <th>Status</th>
                <th>Started</th>
                <th>Finished</th>
                <th>
                  <span className="sr-only">Watch</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {runs.data?.map((r) => (
                <tr key={r.id}>
                  <td className="mono">{r.id}</td>
                  <td>{r.stage}</td>
                  <td>
                    <span className={`pill ${r.status === "done" ? "ok" : r.status === "failed" ? "bad" : "info"}`}>{r.status}</span>
                  </td>
                  <td className="mono">{r.started_at}</td>
                  <td className="mono">{r.finished_at ?? "—"}</td>
                  <td>
                    <Link to={`/projects/${encodeURIComponent(slug)}/live?session=${encodeURIComponent(`job-${r.id}-${r.stage}`)}`} aria-label={`Watch run ${r.id}`}>
                      watch
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
