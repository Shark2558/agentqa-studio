import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useBackdropClose } from "../../lib/useBackdropClose";

type Props = {
  label: string;
  className: string;
  /** The id of text that describes the dialog (read after its name), e.g. a warning inside it. */
  describedBy?: string;
  /** Escape and a click on the backdrop: the help box only minimises, it never answers for the person. */
  onEscape: () => void;
  children: ReactNode;
};

const FOCUSABLE = "button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href]";

/** Where the focus goes when a dialog closes (WCAG 2.4.3): to what had it before, if that is still on the page, and
 *  otherwise to the page's heading (made focusable for the purpose), so it never drops onto nothing. */
function giveFocusBack(opener: Element | null): void {
  if (opener instanceof HTMLElement && opener !== document.body && opener.isConnected) {
    opener.focus();
    return;
  }
  const heading = document.querySelector<HTMLElement>("main h1") ?? document.querySelector<HTMLElement>("h1");
  if (!heading) return;
  if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
  heading.focus();
}

/** The Lightbox pattern (M1.3), for the help box: a modal dialog in a portal over a page closed to the keyboard
 *  (`inert`); focus starts on its first control and stays inside it; Escape or the backdrop calls `onEscape`. When it
 *  closes the page is opened again first and only then the focus goes back. It mounts once per opening, so the polled
 *  list refreshing behind it never moves the focus. */
export function Modal({ label, className, describedBy, onEscape, children }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const escape = useRef(onEscape);
  useEffect(() => {
    escape.current = onEscape;
  });
  useEffect(() => {
    const page = document.getElementById("root");
    const opener = document.activeElement;
    page?.setAttribute("inert", "");
    box.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") escape.current();
      if (e.key === "Tab") keepFocusInside(e, box.current);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      page?.removeAttribute("inert");
      giveFocusBack(opener);
    };
  }, []);
  const backdrop = useBackdropClose(() => escape.current());
  return createPortal(
    // oxlint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions -- the backdrop; Escape is the keyboard's way out
    <div className={`assist-backdrop ${className}`} role="dialog" aria-modal="true" aria-label={label} aria-describedby={describedBy}
         onMouseDown={backdrop.onMouseDown} onClick={backdrop.onClick}>
      <div ref={box} className="assist-panel">{children}</div>
    </div>,
    document.body,
  );
}

function keepFocusInside(e: KeyboardEvent, box: HTMLElement | null) {
  const items = box ? [...box.querySelectorAll<HTMLElement>(FOCUSABLE)] : [];
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}
