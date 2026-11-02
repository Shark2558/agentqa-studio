import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Sparkle } from "@phosphor-icons/react";
import { ApiError, api } from "../lib/api";

export function Projects() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const create = useMutation({
    mutationFn: () => api.createProject(name, url),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${encodeURIComponent(project.slug)}`);
    },
  });
  const demo = useMutation({
    mutationFn: api.createDemo,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${encodeURIComponent(project.slug)}`);
    },
  });
  const error = [create.error, demo.error].find((e) => e instanceof ApiError) as ApiError | undefined;

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
      </div>

      <div className="grid g-two">
        <section className="card flat" aria-labelledby="h-list">
          <h2 id="h-list">Your projects</h2>
          {projects.isPending && <p className="muted">Loading…</p>}
          {projects.data?.length === 0 && <p className="muted">No projects yet. Create one, or try the demo.</p>}
          <ul className="list">
            {projects.data?.map((p) => (
              <li key={p.slug}>
                <Link to={`/projects/${encodeURIComponent(p.slug)}`} className="list-row">
                  <span>
                    <b>{p.name}</b>
                    <span className="muted small mono">{p.url}</span>
                  </span>
                  <span className="muted small">
                    {p.cases != null ? `${p.cases} cases · ${p.defects} open defects` : "new"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <form
          className="card"
          aria-labelledby="h-new"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <h2 id="h-new">New project</h2>
          <label htmlFor="name">Name</label>
          <input id="name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
          <label htmlFor="url">Application address</label>
          <input id="url" type="url" required placeholder="https://uat.example.gov.in" value={url} onChange={(e) => setUrl(e.target.value)} />
          <p className="muted small">Test or UAT environments only, unless you own the live site and have marked it production.</p>
          {error && (
            <p className="notice bad" role="alert">
              {error.message}
            </p>
          )}
          <button className="btn primary" type="submit" disabled={create.isPending}>
            <Plus aria-hidden="true" />
            Create project
          </button>
        </form>
      </div>
    </>
  );
}
