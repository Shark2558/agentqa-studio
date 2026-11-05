import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { WHY_MAX, cleanWhy } from "../../lib/gates";

type Props = {
  /** A question; text from the tested site inside it goes in `<bdi>`, so it keeps its own direction. */
  title: ReactNode;
  confirmLabel: string;
  isRequired: boolean;
  isBusy?: boolean;
  onConfirm: (why: string) => void;
  onCancel: () => void;
};

/** "Why?" before a decision that rejects, undoes or overrides (decision 4). A small non-modal panel in place: the
 *  reason box takes focus; Escape or Cancel closes it. The control that opened it puts focus back (it knows itself;
 *  `document.activeElement` is the page in browsers that do not focus a clicked button). */
export function ReasonDialog({ title, confirmLabel, isRequired, isBusy = false, onConfirm, onCancel }: Props) {
  const id = useId();
  const [text, setText] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  const cancel = useRef(onCancel);
  useEffect(() => {
    cancel.current = onCancel;
  });
  useEffect(() => {
    const box = panel.current;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      cancel.current();
    };
    box?.addEventListener("keydown", onKey);
    return () => box?.removeEventListener("keydown", onKey);
  }, []);
  const why = cleanWhy(text);
  const blocked = isBusy || (isRequired && !why);
  return (
    <div ref={panel} role="dialog" aria-labelledby={`${id}-title`} className="reason">
      <form onSubmit={(e) => { e.preventDefault(); if (!blocked) onConfirm(why); }}>
        <p id={`${id}-title`} className="reason-title">{title}</p>
        <label htmlFor={`${id}-why`}>{isRequired ? "Why? (a short reason is required)" : "Why? (optional)"}</label>
        <textarea id={`${id}-why`} rows={2} maxLength={WHY_MAX} required={isRequired} autoFocus value={text}
                  onChange={(e) => setText(e.target.value)} />
        <div className="row">
          <button type="submit" className="btn sm primary" disabled={blocked}>{confirmLabel}</button>
          <button type="button" className="btn sm" onClick={onCancel}>Cancel</button>
        </div>
      </form>
    </div>
  );
}

type ButtonProps = {
  label: string;
  /** The accessible name when the visible label needs its object, e.g. "Reject every a11y_basic case". */
  name?: string;
  title: ReactNode;
  confirmLabel: string;
  isRequired?: boolean;
  isDisabled?: boolean;
  isBusy?: boolean;
  className?: string;
  onConfirm: (why: string) => void;
};

/** A button that asks why first, then decides. The panel closes when the button is disabled (its selection was
 *  cleared, another decision is running), so it never offers a decision about nothing. */
export function WhyButton({ label, name, title, confirmLabel, isRequired = true, isDisabled = false, isBusy, className = "btn sm", onConfirm }: ButtonProps) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const close = () => {
    setOpen(false);
    button.current?.focus();
  };
  return (
    <span className="why-button">
      <button ref={button} type="button" className={className} aria-label={name} aria-expanded={open && !isDisabled} disabled={isDisabled}
              onClick={() => setOpen((o) => !o)}>
        {label}
      </button>
      {open && !isDisabled && (
        <ReasonDialog title={title} confirmLabel={confirmLabel} isRequired={isRequired} isBusy={isBusy}
                      onConfirm={(why) => { close(); onConfirm(why); }} onCancel={close} />
      )}
    </span>
  );
}
