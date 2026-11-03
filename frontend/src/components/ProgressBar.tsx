import type { CSSProperties } from "react";

type Props = {
  /** 0..1; anything outside is clamped, NaN counts as 0. */
  value: number;
  label: string;
};

/** A bar that fills by a transform (compositor-friendly, see styles/components.css .progress), announced as a progress bar. */
export function ProgressBar({ value, label }: Props) {
  const fraction = Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
  return (
    <div className="progress" role="progressbar" aria-label={label} aria-valuenow={Math.round(fraction * 100)} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ "--p": String(fraction) } as CSSProperties} />
    </div>
  );
}
