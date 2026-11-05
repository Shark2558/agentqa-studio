import { useId, useRef, useState, type MouseEvent } from "react";
import { scalePoint, type Point } from "../../lib/assist";

type Props = {
  src: string;
  vw: number;
  vh: number;
  hasShot: boolean;
  label: string;
  /** Given: a click on the picture is a click at that place in the agent's browser (scaled to its size). */
  onPoint?: (p: Point) => void;
  isDisabled?: boolean;
  /** Ids (space-separated) of the lists of buttons that do the same by keyboard: the picture is described by them. */
  describedBy?: string;
};

const KEYBOARD_HINT = "To click by keyboard or screen reader, use the buttons below the picture.";
export const KEYBOARD_HELP = "You cannot point with the keyboard here: use the buttons below instead.";

/** The agent's screen as it is now, at its own size (width and height given, so nothing jumps while it loads). Its
 *  address changes only with a new picture, so the browser fetches it again only then. A click goes to the browser,
 *  measured on the picture itself (not on the frame around it); the second click of a double click is ignored. A
 *  keyboard user has the "On the screen" buttons instead, which the picture says it is described by; an activation
 *  without a place (Enter, a screen reader) is answered in words, not ignored. */
export function ScreenShot({ src, vw, vh, hasShot, label, onPoint, isDisabled = false, describedBy = "" }: Props) {
  const [broken, setBroken] = useState<string | null>(null);
  const [help, setHelp] = useState("");
  const hint = useId();
  const picture = useRef<HTMLImageElement>(null);
  if (!hasShot) return <div className="assist-shot empty">No screenshot yet</div>;
  if (broken === src) return <div className="assist-shot empty">The screenshot is not available just now</div>;
  const img = <img ref={picture} src={src} alt={label} width={vw} height={vh} onError={() => setBroken(src)} />;
  if (!onPoint) return <div className="assist-shot">{img}</div>;
  const click = (e: MouseEvent<HTMLButtonElement>) => {
    if (e.detail === 0) {                               // a key press on the button has no place on the screen
      setHelp(KEYBOARD_HELP);
      return;
    }
    const shown = picture.current?.getBoundingClientRect();
    if (e.detail > 1 || !shown) return;                 // the second click of a double click
    const p = scalePoint({ x: e.clientX - shown.left, y: e.clientY - shown.top }, shown, { vw, vh });
    if (!p) return;
    setHelp("");
    onPoint(p);
  };
  return (
    <>
      <button type="button" tabIndex={-1} className="assist-shot clickable" aria-label={`Click on the screen where you want: ${label}`}
              aria-describedby={`${hint} ${describedBy}`.trim()} disabled={isDisabled} onClick={click}>
        {img}
      </button>
      <span id={hint} className="sr-only">{KEYBOARD_HINT}</span>
      <p role="status" aria-label="Screenshot help" className={help ? "small muted" : "sr-only"}>{help}</p>
    </>
  );
}
