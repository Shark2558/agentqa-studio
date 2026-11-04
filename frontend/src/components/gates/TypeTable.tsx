import type { TypeRow } from "../../lib/gatesApi";
import { WhyButton } from "./ReasonDialog";

type Props = {
  types: readonly TypeRow[];
  mayWrite: boolean;
  isBusy: boolean;
  onDecide: (ctype: string, decision: "approve" | "reject", why: string) => void;
};

/** Every case type with its counts, and (for a person who may decide) approve or reject a whole type at once. Rows
 *  stack into blocks under 1 024 px (`.rows`), so no control scrolls out of its card. */
export function TypeTable({ types, mayWrite, isBusy, onDecide }: Props) {
  return (
    <table className="rows type-table">
      <caption className="sr-only">Cases by type</caption>
      <thead>
        <tr>
          <th scope="col">Type</th>
          <th scope="col">Cases</th>
          <th scope="col">Decided</th>
          {mayWrite && <th scope="col"><span className="sr-only">Decide the whole type</span></th>}
        </tr>
      </thead>
      <tbody>
        {types.map((t) => (
          <tr key={t.type}>
            <td className="lead mono">{t.type}</td>
            <td data-label="Cases">{t.cases}</td>
            <td className="wrap" data-label="Decided">{t.approved} approved · {t.rejected} rejected · {t.proposed} to review</td>
            {mayWrite && (
              <td className="type-actions">
                <button type="button" className="btn sm" aria-label={`Approve every ${t.type} case`} disabled={isBusy}
                        onClick={() => onDecide(t.type, "approve", "")}>
                  Approve
                </button>
                <WhyButton label="Reject" name={`Reject every ${t.type} case`} title={`Reject all ${t.cases} ${t.type} cases: why?`}
                           confirmLabel={`Reject all ${t.cases} ${t.type} cases`} isDisabled={isBusy} isBusy={isBusy}
                           onConfirm={(why) => onDecide(t.type, "reject", why)} />
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
