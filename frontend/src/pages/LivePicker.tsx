import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { ProjectList } from "../components/ProjectList";

/** `/live` outside a project: Live View shows one project's run, so choose the project first. */
export function LivePicker() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  return (
    <>
      <div className="topbar">
        <div>
          <div className="crumbs">
            <Link to="/">Projects</Link> / <b>Live View</b>
          </div>
          <h1>Live View</h1>
          <p className="sub">Live View shows one project's run. Choose the project to watch.</p>
        </div>
      </div>
      <section className="card" aria-labelledby="h-pick">
        <h2 id="h-pick">Which project?</h2>
        <ProjectList
          projects={projects.data}
          isPending={projects.isPending}
          isError={projects.isError}
          hrefFor={(slug) => `/projects/${encodeURIComponent(slug)}/live`}
          emptyText="There is no project yet, so nothing can run."
        />
      </section>
    </>
  );
}
