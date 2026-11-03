import { Link, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Sparkle } from "@phosphor-icons/react";
import { ApiError, api } from "../lib/api";
import { ProjectList } from "../components/ProjectList";

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
        <ProjectList
          projects={projects.data}
          isPending={projects.isPending}
          hrefFor={(slug) => `/projects/${encodeURIComponent(slug)}`}
          emptyText="No projects yet: the six-step wizard builds one, or try the demo."
        />
      </section>
    </>
  );
}
