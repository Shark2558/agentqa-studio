import { memo, useId } from "react";
import { when } from "../../lib/gates";
import { reviewFiles, type Picture as Which, type VisualDecision, type VisualItem } from "../../lib/reviewApi";
import { Picture } from "./Picture";
import { WhyButton } from "./ReasonDialog";

const STATUS: Readonly<Record<string, [tone: string, words: string]>> = {
  changed: ["warn", "changed"], approved: ["ok", "new baseline approved"], reported: ["bad", "reported as a defect"],
  baseline: ["neutral", "first picture"], same: ["ok", "unchanged"],
};
const PERCENT = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 });
const PICTURES: readonly { which: Which; caption: string; alt: (where: string) => string; none: string }[] = [
  { which: "baseline", caption: "Approved", alt: (w) => `The approved baseline of ${w}`, none: "No approved picture" },
  { which: "current", caption: "Now", alt: (w) => `Now: ${w}`, none: "No current picture" },
  { which: "diff", caption: "Difference", alt: (w) => `The difference on ${w}`, none: "No difference picture" },
];

type Props = { slug: string; v: VisualItem; mayWrite: boolean; isBusy: boolean; onDecide: (key: string, d: VisualDecision, why: string, where: string) => void };

/** One screen whose look changed since its approved baseline: the three pictures by key (never by path), how much
 *  differs, and the two decisions. Its address comes from the tested site: text only. */
export const VisualCard = memo(function VisualCard({ slug, v, mayWrite, isBusy, onDecide }: Props) {
  const id = useId();
  const where = `${v.path ?? v.key}${v.role ? ` (${v.role})` : ""}`;
  const [tone, words] = Object.hasOwn(STATUS, v.status) ? STATUS[v.status] : ["neutral", v.status];
  return (
    <article className="card visual-card" aria-labelledby={`${id}-t`}>
      <div className="defect-head">
        <span className={`pill ${tone}`}>{words}</span>
        {v.role && <span className="small">as {v.role}</span>}
        {v.case_id && <span className="mono small">{v.case_id}</span>}
        <span className="small muted">{when(v.updated_at)}</span>
      </div>
      <h3 id={`${id}-t`} className="defect-title mono">{v.path ?? v.key}</h3>
      {v.diff_ratio !== null && v.status !== "baseline" && <p className="small">{PERCENT.format(v.diff_ratio)} of the layout differs</p>}
      <div className="visual-pics">
        {PICTURES.map((p) => (
          <figure key={p.which}>
            {v.images[p.which]
              ? <Picture src={reviewFiles.visual(slug, v.key, p.which)} alt={p.alt(where)} width={320} height={200} />
              : <span className="pic-missing">{p.none}</span>}
            <figcaption className="small muted">{p.caption}</figcaption>
          </figure>
        ))}
      </div>
      {mayWrite && v.status === "changed" && (
        <div className="type-actions">
          <WhyButton label="Approve as the new baseline" name={`Approve as the new baseline: ${where}`} className="btn sm primary"
                     title={<>Keep the new look of <bdi>{where}</bdi> as its baseline?</>} confirmLabel="Keep the new look" isBusy={isBusy}
                     onConfirm={(why) => onDecide(v.key, "approve", why, where)} />
          <WhyButton label="Report as a defect" name={`Report as a defect: ${where}`} title={<>Report the change on <bdi>{where}</bdi> as a defect?</>}
                     confirmLabel="Report it" isRequired={false} isBusy={isBusy} onConfirm={(why) => onDecide(v.key, "defect", why, where)} />
        </div>
      )}
    </article>
  );
});
