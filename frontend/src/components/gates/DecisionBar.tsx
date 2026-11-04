import { WhyButton } from "./ReasonDialog";

export type BarAction<D extends string> = {
  decision: D;
  label: string;
  /** The verb on the confirm button, e.g. "Reject" → "Reject 3 cases". */
  verb: string;
  needsWhy: boolean;
  isPrimary?: boolean;
};

type Props<D extends string> = {
  count: number;
  noun: readonly [one: string, many: string];
  actions: readonly BarAction<D>[];
  isBusy: boolean;
  onDecide: (decision: D, why: string) => void;
  onClear: () => void;
};

/** What to do with the selected rows: one decision for all of them, a reason first where one is required. It sits
 *  after the list it decides (reading order) and stays in sight at the bottom of the window while the list scrolls. */
export function DecisionBar<D extends string>({ count, noun, actions, isBusy, onDecide, onClear }: Props<D>) {
  const things = `${count} ${count === 1 ? noun[0] : noun[1]}`;
  const off = count === 0 || isBusy;
  return (
    <div className="decision-bar" role="group" aria-label={`Decide the selected ${noun[1]}`}>
      <span className="small" role="status">{count ? `${things} selected` : `Select ${noun[1]} to decide them together`}</span>
      {actions.map((a) =>
        a.needsWhy ? (
          // keyed by the count: a panel opened for 3 cases closes when the selection changes
          <WhyButton key={`${a.decision}:${count}`} label={a.label} title={`${a.verb} ${things}: why?`} confirmLabel={`${a.verb} ${things}`}
                     isDisabled={off} isBusy={isBusy} onConfirm={(why) => onDecide(a.decision, why)} />
        ) : (
          <button key={a.decision} type="button" className={`btn sm${a.isPrimary ? " primary" : ""}`} disabled={off}
                  onClick={() => onDecide(a.decision, "")}>
            {a.label}
          </button>
        ),
      )}
      {count > 0 && <button type="button" className="btn sm" onClick={onClear}>Clear the selection</button>}
    </div>
  );
}
