import { Link } from "react-router";
import type { ProjectSummary } from "../lib/api";

type Props = {
  projects: ProjectSummary[] | undefined;
  isPending: boolean;
  /** Where a row leads: the project page, or its Live View from the picker. */
  hrefFor: (slug: string) => string;
  emptyText: string;
};

/** The project rows, shared by the Projects page and the Live View picker. */
export function ProjectList({ projects, isPending, hrefFor, emptyText }: Props) {
  if (isPending) return <p className="muted">Loading…</p>;
  if (!projects?.length) {
    return (
      <p className="muted">
        {emptyText} <Link to="/projects/new">New project</Link>
      </p>
    );
  }
  return (
    <ul className="list">
      {projects.map((p) => (
        <li key={p.slug}>
          <Link to={hrefFor(p.slug)} className="list-row">
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
  );
}
