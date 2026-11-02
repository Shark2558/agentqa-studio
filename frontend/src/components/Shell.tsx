import { NavLink, useNavigate, useParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Pulse, SignOut } from "@phosphor-icons/react";
import { api } from "../lib/api";
import { useMe } from "../App";

interface ShellProps {
  children: React.ReactNode;
}

/** The app frame: brand, project chip, navigation and the signed-in person. Built from the M0.4 shell recipe. */
export function Shell({ children }: ShellProps) {
  const me = useMe();
  const { slug } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  async function signOut() {
    try {
      await api.logout();
    } catch {
      // An expired session or a network blip must not keep the person signed in on this screen.
    } finally {
      queryClient.clear();
      navigate("/sign-in", { replace: true });
    }
  }

  return (
    <div className="shell">
      <nav className="side" aria-label="Main">
        <NavLink className="brand" to="/">
          <span className="mark" aria-hidden="true">AQ</span>
          <span>
            <span className="brand-name">AgentQA Studio</span>
            <span className="brand-tag">Agents that test like people</span>
          </span>
        </NavLink>
        <div className="nav">
          <div className="nav-sect">Overview</div>
          <NavLink to="/" end>
            <FolderOpen aria-hidden="true" />
            Projects
          </NavLink>
          {slug && (
            <NavLink to={`/projects/${encodeURIComponent(slug)}/live`}>
              <Pulse aria-hidden="true" />
              Live View
            </NavLink>
          )}
        </div>
        <div className="side-foot">
          <span className="muted small">{me.data?.email}</span>
          <button className="btn sm" type="button" onClick={signOut}>
            <SignOut aria-hidden="true" />
            Sign out
          </button>
        </div>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
