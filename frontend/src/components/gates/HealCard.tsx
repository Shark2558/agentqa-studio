import { memo, useId } from "react";
import { when } from "../../lib/gates";
import type { Heal, HealDecision, HealValues } from "../../lib/reviewApi";
import { WhyButton } from "./ReasonDialog";

const KIND: Readonly<Record<string, string>> = { locator: "A renamed field", workflow: "A workflow step", manual: "Check by hand" };
const STATUS: Readonly<Record<string, [tone: string, words: string]>> = {
  proposed: ["info", "to decide"], approved: ["ok", "approved"], rejected: ["neutral", "rejected"],
};

const str = (v: HealValues[string] | undefined): string => (v === null || v === undefined ? "" : String(v));
const named = (field: string, label: string) => (label && label !== field ? `${field} (${label})` : field);

/** What the fix changes, in the engine's own words: a field renamed, a workflow step's control, or a message. */
function beforeAfter(h: Heal): { title: string; before: string; after: string } {
  if (h.kind === "locator") {
    return { title: `On ${str(h.old.path) || "a screen"}`, before: named(str(h.old.field), str(h.old.label)), after: named(str(h.new.field), str(h.new.label)) };
  }
  if (h.kind === "workflow") {
    return { title: `Workflow ${str(h.old.workflow)}, step ${str(h.old.step)}`, before: str(h.old.value), after: str(h.new.value) };
  }
  return { title: "This test needs a person", before: str(h.old.message) || str(h.old.field), after: "" };
}

type Props = { h: Heal; mayWrite: boolean; isBusy: boolean; onDecide: (id: number, d: HealDecision, why: string) => void };

/** One proposed fix for a test a changed screen broke. Approving never changes what a test expects; a workflow fix
 *  also writes project.yaml. Values come from the tested site: text only. */
export const HealCard = memo(function HealCard({ h, mayWrite, isBusy, onDecide }: Props) {
  const id = useId();
  const what = beforeAfter(h);
  const [tone, words] = Object.hasOwn(STATUS, h.status) ? STATUS[h.status] : ["neutral", h.status];
  return (
    <article className="card heal-card" aria-labelledby={`${id}-t`}>
      <div className="defect-head">
        <span className="mono">Fix {h.id}</span>
        <span className="pill neutral">{Object.hasOwn(KIND, h.kind) ? KIND[h.kind] : h.kind}</span>
        <span className={`pill ${tone}`}>{words}</span>
        <span className="small muted">{when(h.created_at)}</span>
      </div>
      <h3 id={`${id}-t`} className="defect-title">{what.title}</h3>
      <dl className="review">
        <dt>Test cases</dt><dd className="mono">{h.case_id || "—"}</dd>
        <dt>{h.kind === "manual" ? "What happened" : "Before"}</dt><dd className="mono">{what.before || "—"}</dd>
        {h.kind !== "manual" && <><dt>After</dt><dd className="mono">{what.after || "—"}</dd></>}
      </dl>
      <p className="small heal-reason">{h.reason}</p>
      {h.kind === "manual" && <p className="small muted">AgentQA cannot fix this one: check this test by hand.</p>}
      {mayWrite && h.decidable && (
        <div className="type-actions">
          <button type="button" className="btn sm primary" aria-label={`Approve the fix ${h.id}`} disabled={isBusy} onClick={() => onDecide(h.id, "approve", "")}>
            Approve the fix
          </button>
          <WhyButton label="Reject" name={`Reject fix ${h.id}`} title={`Reject fix ${h.id}?`} confirmLabel="Reject the fix" isBusy={isBusy}
                     onConfirm={(why) => onDecide(h.id, "reject", why)} />
        </div>
      )}
    </article>
  );
});
