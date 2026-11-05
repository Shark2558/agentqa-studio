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

/** The questions in `items` not yet said for this project. */
function unsaid(slug: string, items: readonly Waiting[]): readonly Waiting[] {
  const seen = announced.get(slug);
  return seen ? items.filter((i) => !seen.has(i.id)) : items;
}

/** Every new question is said once (in the dock's live region, which sits outside the page a dialog closes), and
 *  notified; a list that is only asked again says nothing. Nothing is said before the role is known: what a Viewer
 *  hears differs from what the owner hears. The words are worked out while rendering, when the project or the
 *  questions change (React's pattern for adjusting state when a value changes); the effect only records them as said
 *  and notifies. The change is told by the question ids, never by the list itself: a caller may hand a new empty list
 *  on every render while nothing has loaded, and comparing lists would then set state forever. */
export function useNews(slug: string, items: readonly Waiting[], mayDrive: boolean, isRoleKnown: boolean): string {
  const key = [slug, ...items.map((i) => i.id)].join(" ");
  const [news, setNews] = useState<{ key: string | null; text: string }>({ key: null, text: "" });
  if (isRoleKnown && news.key !== key) {
    const fresh = unsaid(slug, items);
    setNews({ key, text: fresh.length ? fresh.map((i) => said(i, mayDrive)).join(" ") : news.text });
  }
  useEffect(() => {
    if (!isRoleKnown) return;
    const fresh = unsaid(slug, items);
    if (!fresh.length) return;
    announced.set(slug, new Set([...(announced.get(slug) ?? []), ...fresh.map((i) => i.id)]));
    fresh.forEach(notify);
  }, [slug, items, isRoleKnown]);
  return news.text;
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
