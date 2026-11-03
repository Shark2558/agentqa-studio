import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { Palette } from "@phosphor-icons/react";
import { ACCENTS, MODES, MODE_LABELS, accentLabel, useTheme, type ThemePreference } from "../lib/theme";

type Props = {
  /** Where the panel opens: `up` from a sidebar foot (in normal flow), `down` from a top bar (floating). */
  placement?: "up" | "down";
};

type FieldProps = { id: string; pref: ThemePreference; onChange: (pref: ThemePreference) => void };

function ModeField({ id, pref, onChange }: FieldProps) {
  return (
    <fieldset>
      <legend>Theme</legend>
      <div className="modes">
        {MODES.map((mode) => (
          <label key={mode}>
            <input type="radio" name={`${id}-mode`} value={mode} checked={pref.mode === mode} onChange={() => onChange({ ...pref, mode })} />
            <span>{MODE_LABELS[mode]}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function AccentField({ id, pref, onChange }: FieldProps) {
  return (
    <fieldset>
      <legend>Colour: {accentLabel(pref.accent)}</legend>
      <div className="swatches">
        {ACCENTS.map((accent) => (
          <label key={accent.id} title={accent.label} aria-label={accent.label}>
            <input type="radio" name={`${id}-accent`} value={accent.id} checked={pref.accent === accent.id} onChange={() => onChange({ ...pref, accent: accent.id })} />
            <span>
              <i style={{ "--sw": accent.swatch } as CSSProperties} aria-hidden="true" />
              <span className="sr-only">{accent.label}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** While the panel is open: a tap or click outside closes it; Escape closes it from anywhere and returns focus. */
function useDismiss(open: boolean, root: React.RefObject<HTMLDivElement | null>, close: (refocus: boolean) => void) {
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (e.target instanceof Node && !root.current?.contains(e.target)) close(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(true);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, root, close]);
}

/** The Appearance menu: theme (Light / Dark / System) and accent (five named swatches), applied at once and remembered. */
export function ThemeMenu({ placement = "up" }: Props) {
  const [pref, setPref] = useTheme();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const id = useId();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) panel.current?.scrollIntoView?.({ block: "nearest" });   // the sidebar scrolls: bring the panel into view
  }, [open]);
  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) button.current?.focus();
  };
  useDismiss(open, root, close);

  return (
    <div
      className={`appearance ${placement}`}
      ref={root}
      onBlur={(e) => {
        if (open && e.relatedTarget instanceof Node && !root.current?.contains(e.relatedTarget)) setOpen(false);
      }}
    >
      <button ref={button} type="button" className="btn sm appear-btn" aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => setOpen((o) => !o)}>
        <Palette aria-hidden="true" />
        <span className="label">Appearance</span>
      </button>
      {open && (
        <div ref={panel} className="panel" id={id} role="group" aria-label="Appearance">
          <ModeField id={id} pref={pref} onChange={setPref} />
          <AccentField id={id} pref={pref} onChange={setPref} />
          <div className="preview" aria-hidden="true">
            <span className="btn sm primary">Run</span>
            <span className="pill info">running</span>
            <span className="link-sample">a link</span>
          </div>
        </div>
      )}
    </div>
  );
}
