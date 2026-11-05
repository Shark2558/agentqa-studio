import { useCallback, useState } from "react";
import { useParams } from "react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMe } from "../../App";
import { canWrite } from "../../lib/can";
import { errorWords, isStale } from "../../lib/gates";
import { reviewApi, type VisualDecision, type VisualShow } from "../../lib/reviewApi";
import { useGateCounts, useRefreshWhenRunEnds } from "../../lib/useGateCounts";
import { Announce } from "../../components/gates/Announce";
import { GateTop } from "../../components/gates/GateTop";
import { WhyButton } from "../../components/gates/ReasonDialog";
import { VisualCard } from "../../components/gates/VisualCard";

const KEYS = ["visual", "changes"] as const;
const SHOWS: readonly { id: VisualShow; label: string }[] = [
  { id: "changed", label: "Changed" }, { id: "approved", label: "Approved" }, { id: "reported", label: "Reported" },
  { id: "baseline", label: "First pictures" }, { id: "same", label: "Unchanged" }, { id: "all", label: "All" },
];

type Decision = { key: string; decision: VisualDecision; why: string; where: string };

/** What "approve every changed screen" did, in words: how many were kept, and how many could not be (they still need a
 *  decision). */
function keptWords(approved: number, skipped: number): { text: string; warning: string } {
  const kept = `Kept ${approved} new look${approved === 1 ? "" : "s"}.`;
  if (skipped <= 0) return { text: kept, warning: "" };
  const text = `${kept} ${skipped} screen${skipped === 1 ? "" : "s"} could not be kept and still need${skipped === 1 ? "s" : ""} a decision.`;
  return { text, warning: text };
}

/** The decisions on changed screens. `decide` keeps its identity from one render to the next (it hangs on the
 *  mutation's own stable `mutate`, not on the whole result, which is new every time), so the memoised cards are not
 *  drawn again for nothing. */
export function useVisualDecisions(slug: string, done: (text: string, warning: string) => void) {
  const queryClient = useQueryClient();
  const refresh = () => {
    for (const key of [...KEYS, "gates", "defects"]) queryClient.invalidateQueries({ queryKey: [key, slug] });
  };
  const one = useMutation({
    mutationFn: ({ key, decision, why }: Decision) => reviewApi.decideVisual(slug, key, decision, why),
    onSuccess: (r, { where }) => { refresh(); done(r.defect ? `Reported as ${r.defect}.` : `Kept the new look of ${where}.`, ""); },
    onError: (e) => { if (isStale(e)) refresh(); },
  });
  const all = useMutation({
    mutationFn: (why: string) => reviewApi.approveAllVisual(slug, why),
    onSuccess: (r) => {
      refresh();
      const words = keptWords(r.approved, r.skipped);
      done(words.text, words.warning);
    },
    onError: (e) => { if (isStale(e)) refresh(); },
  });
  const { mutate } = one;
  const decide = useCallback((key: string, decision: VisualDecision, why: string, where: string) => mutate({ key, decision, why, where }), [mutate]);
  return { one, all, decide };
}

/** Visual review: a screen whose look changed since its approved picture is kept as the new baseline (with a reason,
 *  decision 4) or reported as a defect. A run writes these screens itself, so a decision waits while one goes. */
export function Visual() {
  const { slug = "" } = useParams();
  const mayWrite = canWrite(useMe().data?.role);
  const [show, setShow] = useState<VisualShow>("changed");
  const [news, setNews] = useState("");
  const [warning, setWarning] = useState("");
  const view = useQuery({ queryKey: ["visual", slug, show], queryFn: () => reviewApi.visual(slug, show), placeholderData: keepPreviousData });
  const running = useGateCounts(slug).data?.running;
  useRefreshWhenRunEnds(slug, running, KEYS);
  const { one, all, decide } = useVisualDecisions(slug, (text, warn) => { setNews(text); setWarning(warn); });
  const v = view.data;
  const counts = v?.counts ?? {};
  const changed = counts.changed ?? 0;
  const tabCount = (id: VisualShow) => (id === "all" ? Object.values(counts).reduce((n, c) => n + c, 0) : counts[id] ?? 0);
  const busy = one.isPending || all.isPending || !!running;
  const error = one.error ?? all.error;
  return (
    <>
      <GateTop slug={slug} title="Visual review" sub={v ? `${changed} changed screen${changed === 1 ? "" : "s"} to review` : "Loading…"}>
        {mayWrite && changed > 0 && (
          <WhyButton label="Approve every changed screen" title={`Keep the new look of all ${changed} changed screens?`}
                     confirmLabel={`Keep all ${changed} new looks`} className="btn sm" isBusy={busy} onConfirm={(why) => all.mutate(why)} />
        )}
      </GateTop>
      <Announce text={news} />
      {view.isError && <p className="notice bad" role="alert">The screens could not be loaded. Reload the page.</p>}
      {running && mayWrite && <p className="notice info">A run is going: decide on the screens once it has finished.</p>}
      {warning && <p className="notice warn">{warning}</p>}
      <div className="filters" role="group" aria-label="Which screens">
        {SHOWS.map((s) => (
          <button key={s.id} type="button" className="filter" aria-pressed={show === s.id} onClick={() => setShow(s.id)}>{s.label} ({tabCount(s.id)})</button>
        ))}
      </div>
      <h2 className="sr-only">Screens</h2>
      {v && v.items.length === 0 && <p className="muted">No screens here.</p>}
      {v && v.total > v.items.length && <p className="small muted">Showing the first {v.items.length} of {v.total}.</p>}
      {error && <p className="notice bad" role="alert">{errorWords(error)}</p>}
      <div className="defect-list">
        {v?.items.map((item) => <VisualCard key={item.key} slug={slug} v={item} mayWrite={mayWrite} isBusy={busy} onDecide={decide} />)}
      </div>
    </>
  );
}
