import { NavLink } from "react-router";
import { FolderOpen, ListChecks, Pulse, SquaresFour } from "@phosphor-icons/react";

type Props = {
  /** The project the person is inside, if any (never the wizard's `new`). */
  slug: string | null;
  /** Called after a link is chosen (the drawer closes itself with it). */
  onNavigate?: () => void;
};

/** The one list of destinations, shared by the sidebar and the phone drawer. Live View is always listed. */
export function NavLinks({ slug, onNavigate }: Props) {
  const project = slug ? `/projects/${encodeURIComponent(slug)}` : null;
  return (
    <div className="nav" onClick={(e) => e.target instanceof Element && e.target.closest("a") && onNavigate?.()}>
      <div className="nav-sect">Overview</div>
      <NavLink to="/" end>
        <FolderOpen aria-hidden="true" />
        Projects
      </NavLink>
      <NavLink to={project ? `${project}/live` : "/live"}>
        <Pulse aria-hidden="true" />
        Live View
      </NavLink>
      {project && (
        <>
          <div className="nav-sect">This project</div>
          <NavLink to={project} end>
            <SquaresFour aria-hidden="true" />
            Overview
          </NavLink>
          <NavLink to={`${project}/requirements`}>
            <ListChecks aria-hidden="true" />
            Requirements
          </NavLink>
        </>
      )}
    </div>
  );
}
