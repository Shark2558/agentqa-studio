import { useSyncExternalStore } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { pollMs } from "./assist";
import { reviewApi } from "./reviewApi";

function onVisibility(cb: () => void) {
  document.addEventListener("visibilitychange", cb);
  return () => document.removeEventListener("visibilitychange", cb);
}

export function usePageVisible(): boolean {
  return useSyncExternalStore(onVisibility, () => document.visibilityState !== "hidden", () => true);
}

type Options = {
  /** True in one place only, the dock: it asks again every 2 s while the tab is seen, every second during a take-over,
   *  every 10 s while it is hidden; stops once signed out. Everyone else reads what the dock asked. */
  poll?: boolean;
};

/** What the agents wait for, shared by the dock on every project page, the Live View's banner and its Pause button.
 *  Without `poll` it only reads the project's list (asking once if nobody has yet), so one project is asked about by
 *  one timer, not three. */
export function useAssist(slug: string | null, { poll = false }: Options = {}) {
  const visible = usePageVisible();
  return useQuery({
    queryKey: ["assist", slug],
    queryFn: () => reviewApi.assist(slug ?? ""),
    enabled: slug !== null,
    refetchIntervalInBackground: true,
    refetchInterval: poll ? (q) => pollMs({ visible, takingOver: !!q.state.data?.items.some((i) => i.kind === "takeover"), error: q.state.error }) : false,
    refetchOnMount: poll,
    refetchOnWindowFocus: poll,
  });
}

// Which waiting question is open in a dialog, and for which project: the dock shows it; the Live View's banner may
// open it too. Another project's page never opens it, and it is forgotten when the dock goes away.
type Opened = { slug: string; id: number };
let opened: Opened | null = null;
const listeners = new Set<() => void>();

function set(next: Opened | null): void {
  opened = next;
  for (const listener of listeners) listener();
}

export function openAssist(slug: string, id: number): void {
  set({ slug, id });
}

export function closeAssist(): void {
  if (opened !== null) set(null);
}

function onOpened(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** The open question's number on this project's pages, or null. */
export function useOpenAssist(slug: string): number | null {
  return useSyncExternalStore(onOpened, () => (opened?.slug === slug ? opened.id : null), () => null);
}

/** What to do once the server has taken an answer: ask for the list again and close the dialog when it has come, so
 *  the dialog and the dock's button for it go in one move and the focus has a place to go; the gate counts follow. */
export function useAnswered(slug: string): () => Promise<void> {
  const queryClient = useQueryClient();
  return async () => {
    void queryClient.invalidateQueries({ queryKey: ["gates", slug] });
    await queryClient.invalidateQueries({ queryKey: ["assist", slug] });
    closeAssist();
  };
}
