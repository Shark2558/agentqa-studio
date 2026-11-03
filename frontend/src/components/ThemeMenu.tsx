import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { Palette } from "@phosphor-icons/react";
import { ACCENTS, MODES, MODE_LABELS, useTheme } from "../lib/theme";

type Props = {
  /** Where the panel opens: `up` from a sidebar foot, `down` from a top bar. */
  placement?: "up" | "down";
};

/** The Appearance menu: theme (Light / Dark / System) and accent (five named swatches), applied at once and
 *  remembered. A non-modal panel: Escape or a click outside closes it; Escape also returns focus to the button. */
export function ThemeMenu({ placement = "up" }: Props) {
  const [pref, setPref] = useTheme();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape" && open) {
      e.stopPropagation();
      setOpen(false);
      button.current?.focus();
    }
  }

  return (
    <div className={`appearance ${placement}`} ref={root} onKeyDown={handleKeyDown}>
      <button ref={button} type="button" className="btn sm appear-btn" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        <Palette aria-hidden="true" />
        Appearance
      </button>
      {open && (
        <div className="panel" id={id} role="group" aria-label="Appearance">
          <fieldset>
            <legend>Theme</legend>
            <div className="modes">
              {MODES.map((mode) => (
                <label key={mode}>
                  <input type="radio" name={`${id}-mode`} value={mode} checked={pref.mode === mode} onChange={() => setPref({ ...pref, mode })} />
                  <span>{MODE_LABELS[mode]}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend>Colour</legend>
            <div className="swatches">
              {ACCENTS.map((accent) => (
                <label key={accent.id} title={accent.label}>
                  <input type="radio" name={`${id}-accent`} value={accent.id} checked={pref.accent === accent.id} onChange={() => setPref({ ...pref, accent: accent.id })} />
                  <span>
                    <i style={{ "--sw": accent.swatch } as CSSProperties} aria-hidden="true" />
                    <span className="sr-only">{accent.label}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
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
