import { Link, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Sparkle } from "@phosphor-icons/react";
import { ApiError, api } from "../lib/api";

export function Projects() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const demo = useMutation({
    mutationFn: api.createDemo,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${encodeURIComponent(project.slug)}`);
    },
  });
  const error = demo.error instanceof ApiError ? demo.error : null;

  return (
    <>
      <div className="topbar">
        <div>
          <div className="crumbs">Projects</div>
          <h1>Projects</h1>
        </div>
        <div className="spacer" />
        <button className="btn" type="button" onClick={() => demo.mutate()} disabled={demo.isPending}>
          <Sparkle aria-hidden="true" />
          Try the demo
        </button>
        <Link className="btn primary" to="/projects/new">
          <Plus aria-hidden="true" />
          New project
        </Link>
      </div>
      {error && (
        <p className="notice bad" role="alert">
          {error.message}
        </p>
      )}

      <section className="card flat" aria-labelledby="h-list">
        <h2 id="h-list">Your projects</h2>
        {projects.isPending && <p className="muted">Loading…</p>}
        {projects.data?.length === 0 && <p className="muted">No projects yet. Press “New project” for the six-step wizard, or try the demo.</p>}
        <ul className="list">
          {projects.data?.map((p) => (
            <li key={p.slug}>
              <Link to={`/projects/${encodeURIComponent(p.slug)}`} className="list-row">
                <span>
                  <b>{p.name}</b>
                  <span className="muted small mono">
                    {p.url}
                    {p.environment ? ` · ${p.environment}` : ""}
                  </span>
                </span>
                <span className="muted small">{p.cases != null ? `${p.cases} cases · ${p.defects} open defects` : "new"}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
