import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMatch } from "react-router";
import { BellRinging } from "@phosphor-icons/react";
import { useMe } from "../../App";
import { whoWaits, type Waiting } from "../../lib/assist";
import { canWrite } from "../../lib/can";
import { closeAssist, openAssist, useAssist, useOpenAssist } from "../../lib/useAssist";
import { useGateCounts } from "../../lib/useGateCounts";
import { AssistDialog } from "./AssistDialog";
import { WATCH_ONLY, useDockHeight, useNews, useWaitingTitle } from "./dockHooks";
import { PauseButton } from "./PauseButton";
import { TakeOver } from "./TakeOver";

/** Asks the browser for notifications, only when the person presses the button. The button goes once it has an answer,
 *  so the focus is handed on (`onDone`) before it is lost. */
function NotifyButton({ onDone }: { onDone: () => void }) {
  const supported = typeof Notification !== "undefined";
  const [permission, setPermission] = useState(supported ? Notification.permission : "denied");
  if (!supported || permission !== "default") return null;
  const ask = async () => {
    try {
      setPermission(await Notification.requestPermission());
    } catch {
      setPermission(Notification.permission);
    }
    onDone();
  };
  return <button type="button" className="btn sm" onClick={() => { void ask(); }}>Tell me with a notification</button>;
}

type ItemProps = { slug: string; first: Waiting; more: number; mayDrive: boolean };

function WaitingItem({ slug, first, more, mayDrive }: ItemProps) {
  if (!mayDrive) return <p className="dock-q">{WATCH_ONLY} ({whoWaits(first)}).</p>;
  return (
    <>
      <p className="dock-who">{whoWaits(first)}</p>
      <p className="dock-q">{first.question}</p>
      <div className="row">
        <button type="button" className="btn sm primary" onClick={() => openAssist(slug, first.id)}>
          {first.kind === "takeover" ? "Take over" : "Open"}
        </button>
        {more > 0 && <span className="small muted">and {more} more waiting</span>}
      </div>
    </>
  );
}

/** What is said aloud: outside the page (`#root`) a dialog closes to the keyboard, or a question arriving while one is
 *  open would never be heard. */
function News({ text }: { text: string }) {
  return createPortal(<p className="sr-only" role="status" aria-label="Help box news">{text}</p>, document.body);
}

/** "AgentQA needs you" on every project page (bottom right; a bar across a phone). It never takes the focus: the
 *  dialog opens only when asked. A Viewer reads that AgentQA waits for the owner or a tester, without the screen.
 *  It is the one place that asks the server what waits (the Live View's banner and Pause only read the answer). */
export function NeedsYouDock({ slug }: { slug: string }) {
  const me = useMe();
  const mayDrive = canWrite(me.data?.role);
  const pending = useAssist(slug, { poll: true });
  const running = !!useGateCounts(slug).data?.running;
  const openedId = useOpenAssist(slug);
  const onLive = !!useMatch("/projects/:slug/live/*");                 // the Live View has its own Pause button
  const dock = useRef<HTMLElement>(null);
  const title = useRef<HTMLParagraphElement>(null);
  const items = pending.data?.items ?? [];
  const paused = pending.data?.paused;
  const open = mayDrive ? items.find((i) => i.id === openedId) ?? null : null;
  const shown = items.length > 0 || !!paused?.on;
  useWaitingTitle(items.length > 0);
  useDockHeight(shown, dock);
  const news = useNews(slug, items, mayDrive, !!me.data);
  useEffect(() => closeAssist, [slug]);                                // forgotten when the dock goes or the project changes
  useEffect(() => {
    // Only a poll that succeeded and no longer lists the question means it was answered elsewhere (or ran out of time);
    // a failed poll keeps the data it had, and with it the dialog and what was typed in it.
    if (openedId !== null && !open && pending.isSuccess) closeAssist();
  }, [openedId, open, pending.isSuccess]);
  return (
    <>
      <News text={news} />
      {shown && (
        <aside ref={dock} className="needs-dock" aria-label="AgentQA needs you">
          <p ref={title} tabIndex={-1} className="dock-title"><BellRinging aria-hidden="true" /> {items.length ? "AgentQA needs you" : "The agents are paused"}</p>
          {items[0] && <WaitingItem slug={slug} first={items[0]} more={items.length - 1} mayDrive={mayDrive} />}
          {mayDrive && !onLive && <PauseButton slug={slug} paused={paused} running={running} />}
          {mayDrive && items.length > 0 && <NotifyButton onDone={() => title.current?.focus()} />}
        </aside>
      )}
      {open && (open.kind === "takeover"
        ? <TakeOver key={open.id} slug={slug} item={open} onMinimise={closeAssist} />
        : <AssistDialog key={open.id} slug={slug} item={open} onMinimise={closeAssist} />)}
    </>
  );
}
