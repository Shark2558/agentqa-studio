import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useMatch, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { List, SignOut } from "@phosphor-icons/react";
import { api } from "../lib/api";
import { useMe } from "../App";
import { ErrorBoundary } from "./ErrorBoundary";
import { NavLinks } from "./NavLinks";
import { NavDrawer } from "./NavDrawer";
import { NeedsYouDock } from "./assist/NeedsYouDock";
import { ThemeMenu } from "./ThemeMenu";

type Props = {
  children: React.ReactNode;
};

const SIDEBAR_QUERY = "(min-width: 760px)";

/** The phone drawer's open state: closes on navigation and when the window grows a sidebar; focus goes back to
 *  the menu button after it closes. */
function useDrawer() {
  const [open, setOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  const { pathname } = useLocation();

  useEffect(() => {
    if (wasOpen.current && !open) menuButton.current?.focus();
    wasOpen.current = open;
  }, [open]);
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(SIDEBAR_QUERY);
    const onChange = (e: MediaQueryListEvent) => e.matches && setOpen(false);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [open]);

  return { open, setOpen, menuButton };
}

function Brand({ tagline = false }: { tagline?: boolean }) {
  return (
    <Link className="brand" to="/">
      <span className="mark" aria-hidden="true">AQ</span>
      <span>
        <span className="brand-name">AgentQA Studio</span>
        {tagline && <span className="brand-tag">Agents that test like people</span>}
      </span>
    </Link>
  );
}

/** The app frame: brand, navigation and the signed-in person. Under 760 px a top bar with a menu button and a drawer;
 *  from 760 px a sticky sidebar. The shell is the element of the parent `/*` route, so it reads the project from the
 *  URL with useMatch (useParams only sees `*` here). */
export function Shell({ children }: Props) {
  const me = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const match = useMatch("/projects/:slug/*");
  const slug = match?.params.slug && match.params.slug !== "new" ? match.params.slug : null;
  const { open, setOpen, menuButton } = useDrawer();

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

  const account = (
    <>
      <span className="muted small">{me.data?.email}</span>
      <button className="btn sm" type="button" onClick={signOut}>
        <SignOut aria-hidden="true" />
        Sign out
      </button>
    </>
  );

  return (
    <div className="shell">
      <header className="topnav" inert={open}>
        <button ref={menuButton} type="button" className="icon-btn menu-btn" aria-label="Menu" aria-expanded={open} aria-controls={open ? "drawer" : undefined} onClick={() => setOpen(true)}>
          <List aria-hidden="true" />
        </button>
        <Brand />
        <ThemeMenu placement="down" />
      </header>
      {open && <NavDrawer slug={slug} onClose={() => setOpen(false)} foot={account} />}
      <nav className="side" aria-label="Main" inert={open}>
        <Brand tagline />
        <NavLinks slug={slug} />
        <div className="side-foot">
          <ThemeMenu />
          {account}
        </div>
      </nav>
      <main className="main" inert={open}>
        {children}
      </main>
      {slug && (
        <div inert={open}>
          <ErrorBoundary resetKey={slug} message="The help box could not be shown. Reloading the page usually helps."><NeedsYouDock slug={slug} /></ErrorBoundary>
        </div>
      )}
    </div>
  );
}
