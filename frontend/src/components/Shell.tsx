import { useEffect, useRef, useState } from "react";
import { NavLink, useMatch, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { List, SignOut } from "@phosphor-icons/react";
import { api } from "../lib/api";
import { useMe } from "../App";
import { NavLinks } from "./NavLinks";
import { NavDrawer } from "./NavDrawer";

type Props = {
  children: React.ReactNode;
};

/** The app frame: brand, navigation and the signed-in person. Under 760 px a top bar with a menu button and a drawer;
 *  from 760 px a sticky sidebar. The shell is the element of the parent `/*` route, so it reads the project from the
 *  URL with useMatch (useParams only sees `*` here). */
export function Shell({ children }: Props) {
  const me = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const match = useMatch("/projects/:slug/*");
  const slug = match?.params.slug && match.params.slug !== "new" ? match.params.slug : null;
  const [open, setOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (wasOpen.current && !open) menuButton.current?.focus();      // focus goes back where the drawer came from
    wasOpen.current = open;
  }, [open]);

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
      <header className="topnav">
        <button
          ref={menuButton}
          type="button"
          className="icon-btn menu-btn"
          aria-label="Menu"
          aria-expanded={open}
          aria-controls="drawer"
          onClick={() => setOpen(true)}
        >
          <List aria-hidden="true" />
        </button>
        <NavLink className="brand" to="/">
          <span className="mark" aria-hidden="true">AQ</span>
          <span className="brand-name">AgentQA Studio</span>
        </NavLink>
      </header>
      {open && <NavDrawer slug={slug} onClose={() => setOpen(false)} />}
      <nav className="side" aria-label="Main">
        <NavLink className="brand" to="/">
          <span className="mark" aria-hidden="true">AQ</span>
          <span>
            <span className="brand-name">AgentQA Studio</span>
            <span className="brand-tag">Agents that test like people</span>
          </span>
        </NavLink>
        <NavLinks slug={slug} />
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
