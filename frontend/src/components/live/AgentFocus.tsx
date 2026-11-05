import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { XCircle } from "@phosphor-icons/react";
import { api } from "../../lib/api";
import { useBackdropClose } from "../../lib/useBackdropClose";
import { displayState } from "../../lib/live/board";
import { eventKey, safeBox, safeShot, severity, type Box, type LiveEvent, type Phase } from "../../lib/live/event";
import type { Lane } from "../../lib/live/lanes";
import type { Model } from "../../lib/live/model";

const PAGE = 300;
const MAX_SHOWN = 3000;                  // "Show earlier" stops here; the Activity tab and the replay reach the rest
const NEAR_BOTTOM = 24;                  // px: a reader this close to the end is following the newest row
const PHASE_WORDS: Readonly<Record<Phase, string>> = {
  thought: "Thought", action: "Action", result: "Result", waiting: "Waiting", lifecycle: "Stage", meta: "Model", note: "Note",
};
const TIME = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export type Shown = { shot: string; box: Box | null; caption: string };
type Open = (shown: Shown, opener: HTMLElement) => void;

function boxStyle(box: Box) {
  return { left: `${(box.x / box.vw) * 100}%`, top: `${(box.y / box.vh) * 100}%`, width: `${(box.width / box.vw) * 100}%`,
           height: `${(box.height / box.vh) * 100}%` };
}

/** The enlarged screenshot: a modal dialog over a page closed to the keyboard (`inert`); Escape, the button or a
 *  click on the backdrop closes it and focus goes back to the screen that opened it. It mounts once per opening, so new events behind it never
 *  move the focus (react review). */
export function Lightbox({ src, shown, onClose, returnFocus }: { src: string; shown: Shown; onClose: () => void; returnFocus: () => void }) {
  const close = useRef<HTMLButtonElement>(null);
  const handlers = useRef({ onClose, returnFocus });
  useEffect(() => {
    handlers.current = { onClose, returnFocus };
  });
  useEffect(() => {
    const page = document.getElementById("root");
    page?.setAttribute("inert", "");
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") handlers.current.onClose();
      if (e.key === "Tab") {
        e.preventDefault();                                   // the close button is the only control
        close.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      page?.removeAttribute("inert");
      handlers.current.returnFocus();
    };
  }, []);
  const backdrop = useBackdropClose(onClose);
  return createPortal(
    // oxlint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions -- a click on the backdrop closes it (M1.3 B22); Escape is the keyboard's way
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={`Screenshot: ${shown.caption}`}
         onMouseDown={backdrop.onMouseDown} onClick={backdrop.onClick}>
      <div className="lightbox-inner">
        <div className="lightbox-bar">
          <span>{shown.caption}</span>
          <button ref={close} type="button" className="btn" onClick={onClose}>Close</button>
        </div>
        <div className="shotwrap">
          <img src={src} alt={`Screenshot: ${shown.caption}`} />
          {shown.box && <span className="box on" style={boxStyle(shown.box)} />}
        </div>
      </div>
    </div>,
    document.body,
  );
}

type FrameProps = { lane: Lane; running: boolean; src: (shot: string) => string; onOpen: Open };

/** One browser: the address (text, never a link), the screen with the element being acted on outlined, the last steps. */
export function BrowserFrame({ lane, running, src, onOpen }: FrameProps) {
  const caption = [lane.role, lane.case, lane.caption].filter(Boolean).join(" · ");
  return (
    <figure className={`frame${running ? " running" : ""}`}>
      <div className="url mono">{lane.url || "about:blank"}</div>
      {lane.shot ? (
        <button type="button" className="shotwrap" onClick={(e) => onOpen({ shot: lane.shot as string, box: lane.box, caption }, e.currentTarget)}
                aria-label={`Enlarge the screen: ${caption}`}>
          <img src={src(lane.shot)} alt="" width={lane.box?.vw ?? 1280} height={lane.box?.vh ?? 720} />
          {lane.box && <span className="box on" style={boxStyle(lane.box)} />}
        </button>
      ) : (
        <div className="shotwrap empty">No screen yet</div>
      )}
      <figcaption>{caption || "Waiting for this browser's first step"}</figcaption>
      {lane.verdict && <p className={`verdict ${lane.verdict.level}`}>{lane.verdict.text}</p>}
      {lane.steps.length > 1 && (
        <ol className="frame-steps" aria-label="Earlier steps">
          {lane.steps.slice(1).map((step, i) => <li key={`${i}-${step}`}>{step}</li>)}
        </ol>
      )}
    </figure>
  );
}

type RowProps = { e: LiveEvent; onOpen: Open; src: (shot: string) => string };

const StreamRow = memo(function StreamRow({ e, onOpen, src }: RowProps) {
  const bad = severity(e) === "bad";
  const shot = safeShot(e.shot);
  return (
    <div className={`evt ${e.phase}${bad ? " fail" : ""}`}>
      <div className="k">{PHASE_WORDS[e.phase]}</div>
      <div>
        <p>
          {e.title}
          {bad && (
            <span className="pill bad">
              <XCircle aria-hidden="true" />
              Failed
            </span>
          )}
        </p>
        <div className="t">{TIME.format(new Date(e.t * 1000))}</div>
        {shot && (
          <button type="button" className="thumb" onClick={(el) => onOpen({ shot, box: safeBox(e), caption: e.title }, el.currentTarget)}
                  aria-label={`Enlarge the screen of: ${e.title}`}>
            <img src={src(shot)} alt="" width={96} height={54} loading="lazy" />
          </button>
        )}
      </div>
    </div>
  );
});

/** Keeps a scrolling list on its newest row while the reader is at the bottom; once they scroll up it stays put. */
function useFollowNewest(rows: unknown) {
  const box = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  const onScroll = useCallback(() => {
    const el = box.current;
    if (el) atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM;
  }, []);
  useLayoutEffect(() => {
    const el = box.current;
    if (el && atBottom.current) el.scrollTop = el.scrollHeight;
  }, [rows]);
  return { box, onScroll };
}

/** An AI switch line the board credited to the chosen agent's card (no key is built for any other line). */
const isCredited = (e: LiveEvent, lines: ReadonlySet<string> | undefined): boolean =>
  e.kind === "switched" && lines !== undefined && lines.size > 0 && lines.has(eventKey(e));

type FocusProps = { slug: string; session: string; model: Model; events: readonly LiveEvent[]; pos: number; agent: string | null; runOver: boolean };

/** "<agent> · what it is doing": its browser frame (when it uses one) and its thought → action → result stream. */
export function AgentFocus({ slug, session, model, events, pos, agent, runOver }: FocusProps) {
  const [limit, setLimit] = useState(PAGE);
  const [shown, setShown] = useState<Shown | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const src = useCallback((shot: string) => api.shotUrl(slug, session, shot), [slug, session]);
  const open = useCallback<Open>((s, el) => {
    opener.current = el;
    setShown(s);
  }, []);
  const card = agent ? model.board.cards.get(agent) : undefined;
  const lanes = [...model.lanes.lanes.values()].filter((l) => !agent || l.agent === agent).sort((a, b) => b.lastT - a.lastT);
  // Before the memo below: a value handed to a function after a memo reads it may count as changed, and the memo is lost.
  const state = card ? displayState(card, model.board, runOver) : null;
  const credited = card?.switchLines;                      // the AI switches made while this agent's stage ran
  const rows = useMemo(() => events.slice(0, pos).filter((e) => e.phase !== "meta" && (!agent || e.agent === agent || isCredited(e, credited))),
                       [events, pos, agent, credited]);
  const visible = useMemo(() => rows.slice(-limit), [rows, limit]);
  const { box, onScroll } = useFollowNewest(visible);
  const earlier = Math.min(rows.length, MAX_SHOWN) - visible.length;
  return (
    <section className="card focus" aria-labelledby="h-focus">
      <h2 id="h-focus">{card ? `${card.label} · what it is doing` : "What is happening"}</h2>
      {lanes[0] && <BrowserFrame lane={lanes[0]} running={state === "running"} src={src} onOpen={open} />}
      {earlier > 0 && (
        <button type="button" className="btn sm" onClick={() => setLimit((n) => Math.min(n + PAGE, MAX_SHOWN))}>
          Show earlier ({earlier} more)
        </button>
      )}
      {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scrolling log must be reachable by keyboard */}
      <div ref={box} onScroll={onScroll} className="stream" role="log" aria-live="off" aria-label={card ? `${card.label} activity` : "Live events"} tabIndex={0}>
        {visible.length === 0 && <p className="muted">Nothing from this agent yet.</p>}
        {visible.map((e) => <StreamRow key={`${e.w}-${e.seq}`} e={e} onOpen={open} src={src} />)}
      </div>
      {shown && <Lightbox src={src(shown.shot)} shown={shown} onClose={() => setShown(null)} returnFocus={() => opener.current?.focus()} />}
    </section>
  );
}
