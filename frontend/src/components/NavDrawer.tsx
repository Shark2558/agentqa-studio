import { useEffect, useRef } from "react";
import { Link } from "react-router";
import { X } from "@phosphor-icons/react";
import { NavLinks } from "./NavLinks";

type Props = {
  slug: string | null;
  onClose: () => void;
  /** The account line and Sign out, so phones lose nothing the sidebar has. */
  foot: React.ReactNode;
};

/** The phone menu: a modal panel over a backdrop. The shell makes everything else inert while it is open, so Tab
 *  stays inside; Escape (from anywhere), the backdrop, the close button or any link closes it, and the shell returns
 *  focus to the menu button. A plain dialog role keeps it testable in jsdom. */
export function NavDrawer({ slug, onClose, foot }: Props) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.body.classList.add("drawer-open");
    panel.current?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.classList.remove("drawer-open");
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  return (
    <>
      <div className="drawer-backdrop" aria-hidden="true" onClick={onClose} />
      <div ref={panel} id="drawer" className="drawer" role="dialog" aria-modal="true" aria-label="Menu" tabIndex={-1}>
        <div className="drawer-head">
          <Link className="brand" to="/" onClick={onClose}>
            <span className="mark" aria-hidden="true">AQ</span>
            <span className="brand-name">AgentQA Studio</span>
          </Link>
          <button type="button" className="icon-btn" aria-label="Close menu" onClick={onClose}>
            <X aria-hidden="true" />
          </button>
        </div>
        <nav aria-label="Menu links">
          <NavLinks slug={slug} onNavigate={onClose} />
        </nav>
        <div className="side-foot">{foot}</div>
      </div>
    </>
  );
}
