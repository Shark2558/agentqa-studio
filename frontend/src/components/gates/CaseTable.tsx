import { memo } from "react";
import type { Selection } from "../../lib/gates";
import type { CaseStatus, TestCase, TypeRow } from "../../lib/gatesApi";

export type CaseFilter = { type?: string; status?: CaseStatus };

const STATUS: readonly { id: CaseStatus | undefined; label: string }[] = [
  { id: undefined, label: "Any status" }, { id: "proposed", label: "To review" }, { id: "approved", label: "Approved" },
  { id: "rejected", label: "Rejected" },
];
const STATUS_PILL: Readonly<Record<string, [string, string]>> = {
  proposed: ["neutral", "to review"], approved: ["ok", "approved"], rejected: ["bad", "rejected"],
};

type Props = {
  types: readonly TypeRow[];
  cases: readonly TestCase[];
  filter: CaseFilter;
  onFilter: (next: CaseFilter) => void;
  selected: Selection;
  /** Both stable (useCallback in the page), so a tick re-renders only the row it changes. */
  onToggle: (id: string) => void;
  onToggleAll: (ids: readonly string[], on: boolean) => void;
  mayWrite: boolean;
};

function Filters({ types, filter, onFilter }: Pick<Props, "types" | "filter" | "onFilter">) {
  const all = types.reduce((n, t) => n + t.cases, 0);
  return (
    <>
      <div className="filters" role="group" aria-label="Case type">
        <button type="button" className="filter" aria-pressed={!filter.type} onClick={() => onFilter({ ...filter, type: undefined })}>
          All types ({all})
        </button>
        {types.map((t) => (
          <button key={t.type} type="button" className="filter" aria-pressed={filter.type === t.type} onClick={() => onFilter({ ...filter, type: t.type })}>
            {t.type} ({t.cases})
          </button>
        ))}
      </div>
      <div className="filters" role="group" aria-label="Case status">
        {STATUS.map((s) => (
          <button key={s.label} type="button" className="filter" aria-pressed={filter.status === s.id} onClick={() => onFilter({ ...filter, status: s.id })}>
            {s.label}
          </button>
        ))}
      </div>
    </>
  );
}

type RowProps = { c: TestCase; isSelected: boolean; mayWrite: boolean; onToggle: (id: string) => void };

const CaseRow = memo(function CaseRow({ c, isSelected, mayWrite, onToggle }: RowProps) {
  const [tone, word] = Object.hasOwn(STATUS_PILL, c.status) ? STATUS_PILL[c.status] : ["neutral", c.status];
  return (
    <tr className={isSelected ? "selected" : undefined}>
      {mayWrite && (
        <td className="pick">
          <input type="checkbox" aria-label={`Select ${c.id}`} checked={isSelected} onChange={() => onToggle(c.id)} />
        </td>
      )}
      <td className="lead mono">{c.id}</td>
      <td className="wrap" data-label="Title">{c.title}</td>
      <td className="mono small" data-label="Type">{c.type}</td>
      <td data-label="Role">{c.role ?? "—"}</td>
      <td data-label="Priority">{c.priority ?? "—"}</td>
      <td data-label="Status"><span className={`pill ${tone}`}>{word}</span></td>
    </tr>
  );
});

/** The cases, filtered by type and status, with a selection box per row for a person who may decide. "Select every
 *  case shown" sits above the table, where it shows at every width (the header row is hidden under 1 024 px). */
export function CaseTable({ types, cases, filter, onFilter, selected, onToggle, onToggleAll, mayWrite }: Props) {
  const ids = cases.map((c) => c.id);
  const allOn = ids.length > 0 && ids.every((id) => selected.has(id));
  return (
    <>
      <Filters types={types} filter={filter} onFilter={onFilter} />
      {mayWrite && ids.length > 0 && (
        <label className="check select-all">
          <input type="checkbox" checked={allOn} onChange={(e) => onToggleAll(ids, e.target.checked)} />
          Select every case shown
        </label>
      )}
      <table className="rows case-table">
        <caption className="sr-only">Test cases</caption>
        <thead>
          <tr>
            {mayWrite && <th scope="col"><span className="sr-only">Select</span></th>}
            <th scope="col">Case</th>
            <th scope="col">Title</th>
            <th scope="col">Type</th>
            <th scope="col">Role</th>
            <th scope="col">Priority</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => <CaseRow key={c.id} c={c} isSelected={selected.has(c.id)} mayWrite={mayWrite} onToggle={onToggle} />)}
        </tbody>
      </table>
    </>
  );
}
