import { useEffect, useRef } from "react";
import { NavLink } from "react-router";
import { X } from "@phosphor-icons/react";
import { NavLinks } from "./NavLinks";

type Props = {
  slug: string | null;
  onClose: () => void;
};

/** The phone menu: a modal panel over a backdrop. Escape, the backdrop, the close button or any link closes it; the
 *  shell returns focus to the menu button. A plain dialog role (not <dialog>) keeps it testable in jsdom and still
 *  moves focus inside on open and locks page scrolling while open. */
export function NavDrawer({ slug, onClose }: Props) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.body.classList.add("drawer-open");
    panel.current?.querySelector<HTMLElement>("a, button")?.focus();
    return () => document.body.classList.remove("drawer-open");
  }, []);

  return (
    <>
      <button type="button" className="drawer-backdrop" aria-label="Close menu" tabIndex={-1} onClick={onClose} />
      <div
        ref={panel}
        id="drawer"
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Menu"
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
      >
        <div className="drawer-head">
          <NavLink className="brand" to="/" onClick={onClose}>
            <span className="mark" aria-hidden="true">AQ</span>
            <span className="brand-name">AgentQA Studio</span>
          </NavLink>
          <button type="button" className="icon-btn" aria-label="Close menu" onClick={onClose}>
            <X aria-hidden="true" />
          </button>
        </div>
        <NavLinks slug={slug} onNavigate={onClose} />
      </div>
    </>
  );
}
