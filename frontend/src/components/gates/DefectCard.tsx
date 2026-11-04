import { memo, useId } from "react";
import { isDecidableDefect, when } from "../../lib/gates";
import { gateFiles, type Defect, type Evidence } from "../../lib/gatesApi";

const SEVERITY_TONE: Readonly<Record<string, string>> = { Critical: "bad", High: "bad", Medium: "info", Low: "neutral" };
const STATUS: Readonly<Record<string, [tone: string, words: string]>> = {
  draft: ["info", "to confirm"], confirmed: ["ok", "confirmed"], rejected: ["neutral", "rejected"],
  exported: ["info", "sent to a tracker"], resolved: ["ok", "resolved"], fixed: ["ok", "fixed"], reopened: ["bad", "reopened"],
};
const look = <T,>(table: Readonly<Record<string, T>>, key: string, fallback: T): T => (Object.hasOwn(table, key) ? table[key] : fallback);

function EvidenceList({ slug, did, items }: { slug: string; did: string; items: readonly Evidence[] }) {
  return (
    <ul className="evidence">
      {items.map((e) => {
        const label = `${e.n + 1}: ${e.kind ?? "file"}${e.role ? ` (${e.role})` : ""}`;
        const href = gateFiles.evidence(slug, did, e.n);
        return (
          <li key={e.n}>
            {e.image ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                <img src={href} alt={`Evidence ${label}`} width={160} height={100} loading="lazy" />
              </a>
            ) : (
              <a href={href} download>Download evidence {label}</a>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function Text({ title, body }: { title: string; body: string | null }) {
  if (!body) return null;
  return (
    <>
      <h4 className="small-heading">{title}</h4>
      <pre className="defect-text">{body}</pre>
    </>
  );
}

type Props = { slug: string; defect: Defect; mayWrite: boolean; isSelected: boolean; onToggle: (id: string) => void };

/** One defect as Triage wrote it. Its title, steps, results and address come from the application under test: text
 *  only, the address never a link. Evidence goes by its number in the list, never by a file path. A defect already
 *  sent to a tracker cannot be decided again (the server answers 409 `exported`), so it has no selection box.
 *  Memoised with a stable `onToggle`: ticking one card re-renders only that card. */
export const DefectCard = memo(function DefectCard({ slug, defect: d, mayWrite, isSelected, onToggle }: Props) {
  const id = useId();
  const [tone, words] = look(STATUS, d.status, ["neutral", d.status]);
  const decidable = mayWrite && isDecidableDefect(d);
  return (
    <article className={`card defect${isSelected ? " selected" : ""}`} aria-labelledby={`${id}-t`}>
      <div className="defect-head">
        {decidable && <input type="checkbox" aria-label={`Select ${d.id}`} checked={isSelected} onChange={() => onToggle(d.id)} />}
        <span className="mono">{d.id}</span>
        <span className={`pill ${look(SEVERITY_TONE, d.severity, "neutral")}`}>{d.severity}</span>
        {d.priority && <span className="mono small">{d.priority}</span>}
        <span className={`pill ${tone}`}>{words}</span>
      </div>
      <h3 id={`${id}-t`} className="defect-title">{d.title}</h3>
      <dl className="review">
        <dt>Role</dt><dd>{d.role ?? "—"}</dd>
        <dt>Address</dt><dd className="mono">{d.url ?? "—"}</dd>
        <dt>Requirements</dt><dd className="mono">{d.req_ids?.join(", ") || "—"}</dd>
        <dt>Test cases</dt><dd className="mono">{d.case_ids?.join(", ") || "—"}</dd>
        <dt>Found</dt><dd>{when(d.created_at)}</dd>
        {d.external_key && <><dt>Tracker</dt><dd className="mono">{d.external_key}</dd></>}
      </dl>
      <Text title="Steps" body={d.steps} />
      <Text title="Expected" body={d.expected} />
      <Text title="Actual" body={d.actual} />
      <Text title="Notes" body={d.notes} />
      {d.evidence.length > 0 && (
        <>
          <h4 className="small-heading">Evidence</h4>
          <EvidenceList slug={slug} did={d.id} items={d.evidence} />
        </>
      )}
    </article>
  );
});
