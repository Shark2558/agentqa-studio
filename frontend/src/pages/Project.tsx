import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Pulse } from "@phosphor-icons/react";
import { ApiError, api } from "../lib/api";

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
  // Until M1.4 brings the approval screens into this app, the gates can only be answered in the old dashboard, so
  // the owner chooses here, visibly, whether this run approves them on its own.
  const [autoApprove, setAutoApprove] = useState(true);
  const start = useMutation({
    mutationFn: () => api.startRun(slug, { scope: "pipeline", policy: "srs_wins", auto_approve: autoApprove }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["runs", slug] });
      navigate(`/projects/${encodeURIComponent(slug)}/live?session=job-${run.id}-${run.stage}`);
    },
  });
  const running = runs.data?.find((r) => r.status === "running");
  const error = start.error instanceof ApiError ? start.error : null;

  if (project.isError) return <p className="notice bad page-pad">That project does not exist.</p>;
  if (!project.data) return <p className="muted page-pad">Loading…</p>;
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
        <label className="check small">
          <input type="checkbox" checked={autoApprove} onChange={(e) => setAutoApprove(e.target.checked)} />
          Approve the gates automatically
        </label>
        <Link className="btn" to={`/projects/${encodeURIComponent(slug)}/live`}>
          <Pulse aria-hidden="true" />
          Live View
        </Link>
        <button className="btn primary" type="button" onClick={() => start.mutate()} disabled={start.isPending || !!running}>
          <Play aria-hidden="true" />
          {running ? "Running…" : "Run full pipeline"}
        </button>
      </div>
      {error && (
        <p className="notice bad" role="alert">
          {error.message}
        </p>
      )}

      <div className="grid g-dash">
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
      </div>

      <section className="card flat mt-4" aria-labelledby="h-runs">
        <h2 id="h-runs">Runs</h2>
        {runs.data?.length === 0 && <p className="muted">Nothing has run yet. Press “Run full pipeline” to start; the demo takes about six minutes.</p>}
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Stage</th>
                <th>Status</th>
                <th>Started</th>
                <th>Finished</th>
                <th></th>
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
                    <Link to={`/projects/${encodeURIComponent(slug)}/live?session=job-${r.id}-${r.stage}`}>watch</Link>
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
