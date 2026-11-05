/** What the dock does besides drawing itself: the tab's title, what is said aloud (and as a notification), and the
 *  dock's height handed to the page so its last row never hides under it. */
import { useEffect, useState, type RefObject } from "react";
import { TITLE, whoWaits, type Waiting } from "../../lib/assist";

export const WATCH_ONLY = "AgentQA is waiting for the owner or a tester";
export const DOCK_HEIGHT_VAR = "--dock-h";

/** While an agent waits the tab's title says so (it shows on the tab bar and the task bar); it goes back after. */
export function useWaitingTitle(isWaiting: boolean) {
  useEffect(() => {
    if (!isWaiting) return;
    const before = document.title;
    document.title = TITLE;
    return () => {
      document.title = before;
    };
  }, [isWaiting]);
}

// Which questions were already said, per project, for as long as the page lives: coming back to a project does not say
// them again.
const announced = new Map<string, ReadonlySet<number>>();

/** Forget what was said (for tests: the page itself never needs to). */
export function forgetAnnounced(): void {
  announced.clear();
}

const said = (w: Waiting, mayDrive: boolean): string => (mayDrive ? `${whoWaits(w)} needs you: ${w.question}` : `${WATCH_ONLY}: ${whoWaits(w)}.`);

/** A notification, when the person asked for them and the tab is hidden. Some browsers (Android Chrome) refuse
 *  `new Notification` altogether; the spoken news still says it, so the refusal is only skipped. */
function notify(w: Waiting): void {
  if (typeof Notification === "undefined" || Notification.permission !== "granted" || document.visibilityState !== "hidden") return;
  try {
    new Notification("AgentQA needs you", { body: `${whoWaits(w)} is waiting`, tag: `agentqa-assist-${w.id}` });
  } catch {
    // "Illegal constructor": no notification here
  }
}

/** Every new question is said once (in the dock's live region, which sits outside the page a dialog closes), and
 *  notified; a list that is only asked again says nothing. Nothing is said before the role is known: what a Viewer
 *  hears differs from what the owner hears. */
export function useNews(slug: string, items: readonly Waiting[], mayDrive: boolean, isRoleKnown: boolean): string {
  const [news, setNews] = useState("");
  useEffect(() => {
    if (!isRoleKnown) return;
    const seen = announced.get(slug) ?? new Set<number>();
    const fresh = items.filter((i) => !seen.has(i.id));
    if (!fresh.length) return;
    announced.set(slug, new Set([...seen, ...fresh.map((i) => i.id)]));
    setNews(fresh.map((i) => said(i, mayDrive)).join(" "));
    fresh.forEach(notify);
  }, [slug, items, mayDrive, isRoleKnown]);
  return news;
}

/** The dock's height as a CSS variable on the page (`--dock-h`), kept up to date as the dock grows or shrinks, and
 *  removed with it: the page pads its end by that much (WCAG 2.4.11: a focused control is never hidden under it). */
export function useDockHeight(isShown: boolean, dock: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = dock.current;
    if (!isShown || !el) return;
    const page = document.documentElement;
    const measure = () => page.style.setProperty(DOCK_HEIGHT_VAR, `${Math.ceil(el.getBoundingClientRect().height)}px`);
    measure();
    const watcher = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    watcher?.observe(el);
    return () => {
      watcher?.disconnect();
      page.style.removeProperty(DOCK_HEIGHT_VAR);
    };
  }, [isShown, dock]);
}
