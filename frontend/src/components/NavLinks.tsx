import { NavLink } from "react-router";
import { FolderOpen, ListChecks, Pulse, Robot, SquaresFour } from "@phosphor-icons/react";

type Props = {
  /** The project the person is inside, if any (never the wizard's `new`). */
  slug: string | null;
  /** Called when a link is chosen (the drawer closes itself with it). */
  onNavigate?: () => void;
};

/** The one list of destinations, shared by the sidebar and the phone drawer. Live View is always listed. */
export function NavLinks({ slug, onNavigate }: Props) {
  const project = slug ? `/projects/${encodeURIComponent(slug)}` : null;
  return (
    <div className="nav">
      <div className="nav-sect">Overview</div>
      <NavLink to="/" end onClick={onNavigate}>
        <FolderOpen aria-hidden="true" />
        Projects
      </NavLink>
      <NavLink to={project ? `${project}/live` : "/live"} onClick={onNavigate}>
        <Pulse aria-hidden="true" />
        Live View
      </NavLink>
      {project && (
        <>
          <div className="nav-sect">This project</div>
          <NavLink to={project} end onClick={onNavigate}>
            <SquaresFour aria-hidden="true" />
            Overview
          </NavLink>
          <NavLink to={`${project}/requirements`} onClick={onNavigate}>
            <ListChecks aria-hidden="true" />
            Requirements
          </NavLink>
          <NavLink to={`${project}/ai`} onClick={onNavigate}>
            <Robot aria-hidden="true" />
            AI
          </NavLink>
        </>
      )}
    </div>
  );
}
