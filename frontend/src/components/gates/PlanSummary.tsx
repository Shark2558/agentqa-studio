import { Link } from "react-router";
import type { PlanGaps, PlanView } from "../../lib/gatesApi";

const sum = (rows: PlanView["types"], key: "cases" | "approved" | "rejected" | "proposed") => rows.reduce((n, r) => n + r[key], 0);

function Ids({ ids, none }: { ids: readonly string[]; none: string }) {
  if (!ids.length) return <p className="small muted">{none}</p>;
  return <ul className="id-chips">{ids.map((id) => <li key={id} className="mono">{id}</li>)}</ul>;
}

function Gaps({ gaps, risks }: { gaps: PlanGaps; risks: readonly string[] }) {
  const notes = [
    ...gaps.workflow.map((w) => (w.req_id && w.req_id !== "-" ? `${w.req_id}: ${w.why}` : w.why)),
    ...gaps.production.map((c) => `Not run on production: ${c.title}`),
  ];
  const unread = gaps.unread.map((d) => `${d.name} (${d.detail || d.status})`);
  return (
    <section className="card flat" aria-labelledby="h-gaps">
      <h2 id="h-gaps">What the plan does not cover yet</h2>
      <h3 className="small-heading">Requirements with no test yet</h3>
      <Ids ids={gaps.untested} none="None: every requirement has at least one test." />
      <h3 className="small-heading">Requirements to clarify</h3>
      <Ids ids={gaps.clarify} none="None." />
      <h3 className="small-heading">Documents AgentQA could not read</h3>
      <Ids ids={unread} none="None." />
      {gaps.missed > 0 && <p className="small">{gaps.missed} rule{gaps.missed === 1 ? "" : "s"} did not become a test case.</p>}
      {notes.length > 0 && (
        <>
          <h3 className="small-heading">Notes</h3>
          <ul className="notes small">{notes.map((n, i) => <li key={`${i}:${n}`}>{n}</li>)}</ul>
        </>
      )}
      {risks.length > 0 && (
        <>
          <h3 className="small-heading">Where the risk is</h3>
          <ul className="notes small">{risks.map((r) => <li key={r}>{r}</li>)}</ul>
        </>
      )}
    </section>
  );
}

type Props = { view: PlanView; slug: string; mayWrite: boolean; isBusy: boolean; onApproveImported: () => void };

/** The plan at a glance: case counts, coverage, the gaps, and the imported manual cases. */
export function PlanSummary({ view, slug, mayWrite, isBusy, onApproveImported }: Props) {
  const s = view.plan.summary;
  const imp = view.imported;
  return (
    <>
      <div className="grid g-dash">
        <div className="card kpi"><div className="label">Test cases</div><div className="value">{sum(view.types, "cases")}</div></div>
        <div className="card kpi"><div className="label">To review</div><div className="value">{sum(view.types, "proposed")}</div></div>
        <div className="card kpi"><div className="label">Approved</div><div className="value">{sum(view.types, "approved")}</div></div>
        <div className="card kpi"><div className="label">Rejected</div><div className="value">{sum(view.types, "rejected")}</div></div>
        <div className="card kpi">
          <div className="label">Requirements covered</div>
          <div className="value small-value">{s ? `${s.requirements_covered ?? 0} of ${s.requirements ?? 0}` : "—"}</div>
          {!!s?.open_questions && (
            <Link className="small" to={`/projects/${encodeURIComponent(slug)}/questions`}>{s.open_questions} open questions at design time</Link>
          )}
        </div>
      </div>
      <div className="grid g-two mt-4">
        <Gaps gaps={view.gaps} risks={s?.risk_notes ?? []} />
        <section className="card flat" aria-labelledby="h-imported">
          <h2 id="h-imported">Imported manual cases</h2>
          <ul className="kpi-list small">
            <li><b>{imp.ready}</b> ready to approve</li>
            <li><b>{imp.review}</b> need a look first</li>
            <li><b>{imp.approved}</b> approved</li>
            <li><b>{imp.rejected}</b> rejected</li>
          </ul>
          {mayWrite && imp.ready > 0 && (
            <button type="button" className="btn" disabled={isBusy} onClick={onApproveImported}>
              Approve the {imp.ready} ready imported cases
            </button>
          )}
        </section>
      </div>
    </>
  );
}
