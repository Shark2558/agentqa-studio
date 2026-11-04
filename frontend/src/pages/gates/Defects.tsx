import { useCallback, useState } from "react";
import { useParams } from "react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMe } from "../../App";
import { canWrite } from "../../lib/can";
import { errorWords, inView, isDecidableDefect, isStale, needsWhy, setMany, toggle, type Selection } from "../../lib/gates";
import { gatesApi, type DefectDecision, type DefectsView } from "../../lib/gatesApi";
import { useGateCounts, useRefreshWhenRunEnds } from "../../lib/useGateCounts";
import { Announce } from "../../components/gates/Announce";
import { DecisionBar, type BarAction } from "../../components/gates/DecisionBar";
import { DefectCard } from "../../components/gates/DefectCard";
import { ExportLinks } from "../../components/gates/ExportLinks";
import { GateTop } from "../../components/gates/GateTop";
import { SelectAll } from "../../components/gates/SelectAll";

const NONE: Selection = new Set();
const KEYS = ["defects", "changes"] as const;
const DEFECT_NOUN = ["defect", "defects"] as const;
const SEVERITIES = ["Critical", "High", "Medium", "Low"] as const;
const TABS: readonly { id: string | undefined; label: string }[] = [
  { id: undefined, label: "All" }, { id: "draft", label: "To confirm" }, { id: "confirmed", label: "Confirmed" }, { id: "rejected", label: "Rejected" },
];
const ACTIONS: readonly BarAction<DefectDecision>[] = [
  { decision: "confirmed", label: "Confirm", verb: "Confirm", needsWhy: needsWhy("defects", "confirmed"), isPrimary: true },
  { decision: "rejected", label: "Reject", verb: "Reject", needsWhy: needsWhy("defects", "rejected") },
  { decision: "draft", label: "Back to draft", verb: "Undo the decision on", needsWhy: needsWhy("defects", "draft") },
];
const DONE: Readonly<Record<DefectDecision, string>> = { confirmed: "Confirmed", rejected: "Rejected", draft: "Sent back to draft:" };

function Counts({ counts }: { counts: DefectsView["counts"] }) {
  const open = counts.open_by_severity;
  return (
    <section className="card flat" aria-labelledby="h-open">
      <h2 id="h-open">Open defects</h2>
      <ul className="kpi-list" aria-label="Open defects by severity">
        {SEVERITIES.map((s) => <li key={s}><b>{open[s] ?? 0}</b> {s}</li>)}
      </ul>
    </section>
  );
}

function useDefectDecisions(slug: string, ids: () => string[], done: (text: string) => void) {
  const queryClient = useQueryClient();
  const refresh = () => { for (const key of [...KEYS, "gates"]) queryClient.invalidateQueries({ queryKey: [key, slug] }); };
  return useMutation({
    mutationFn: ({ decision, why }: { decision: DefectDecision; why: string }) => gatesApi.decideDefects(slug, ids(), decision, why),
    onSuccess: (r, { decision }) => { refresh(); done(`${DONE[decision]} ${r.changed} defect${r.changed === 1 ? "" : "s"}.`); },
    onError: (e) => { if (isStale(e)) refresh(); },
  });
}

/** Gate 3: confirm the defects Triage drafted, reject the false ones with a reason, and download them for a tracker. */
export function Defects() {
  const { slug = "" } = useParams();
  const mayWrite = canWrite(useMe().data?.role);
  const [status, setStatus] = useState<string | undefined>(undefined);
  const [selected, setSelected] = useState<Selection>(NONE);
  const [news, setNews] = useState("");
  const view = useQuery({ queryKey: ["defects", slug, status ?? ""], queryFn: () => gatesApi.defects(slug, status), placeholderData: keepPreviousData });
  useRefreshWhenRunEnds(slug, useGateCounts(slug).data?.running, KEYS);
  const v = view.data;
  const decidable = v?.items.filter(isDecidableDefect).map((d) => d.id) ?? [];
  const chosen = inView(selected, decidable);               // only what is shown and decidable now is ever sent
  const decide = useDefectDecisions(slug, () => chosen, (text) => { setSelected(NONE); setNews(text); });
  const onToggle = useCallback((id: string) => setSelected((s) => toggle(s, id)), []);
  const onToggleAll = useCallback((ids: readonly string[], on: boolean) => setSelected((s) => setMany(s, ids, on)), []);
  const byStatus = v?.counts.by_status ?? {};
  const all = Object.values(byStatus).reduce((n, c) => n + c, 0);
  const tabCount = (id: string | undefined) => (id ? byStatus[id] ?? 0 : all);

  return (
    <>
      <GateTop slug={slug} title="Defects" sub={v ? `${all} defects · ${byStatus.draft ?? 0} to confirm` : "Loading…"} />
      <Announce text={news} />
      {view.isError && <p className="notice bad" role="alert">The defects could not be loaded. Reload the page.</p>}
      <div className="grid g-two">
        {v ? <Counts counts={v.counts} /> : <div />}
        <ExportLinks slug={slug} />
      </div>
      <div className="filters mt-4" role="group" aria-label="Which defects">
        {TABS.map((t) => (
          <button key={t.label} type="button" className="filter" aria-pressed={status === t.id} onClick={() => { setStatus(t.id); setSelected(NONE); }}>
            {t.label} ({tabCount(t.id)})
          </button>
        ))}
      </div>
      <h2 className="sr-only">Defects</h2>
      {v && v.items.length === 0 && <p className="muted">No defects here.</p>}
      {v && v.total > v.items.length && <p className="small muted">Showing the first {v.items.length} of {v.total}.</p>}
      {mayWrite && <SelectAll ids={decidable} selected={selected} noun={DEFECT_NOUN} onToggleAll={onToggleAll} />}
      <div className="defect-list">
        {v?.items.map((d) => <DefectCard key={d.id} slug={slug} defect={d} mayWrite={mayWrite} isSelected={selected.has(d.id)} onToggle={onToggle} />)}
      </div>
      {decide.error && <p className="notice bad" role="alert">{errorWords(decide.error)}</p>}
      {mayWrite && (
        <DecisionBar count={chosen.length} noun={DEFECT_NOUN} actions={ACTIONS} isBusy={decide.isPending} onClear={() => setSelected(NONE)}
                     onDecide={(decision, why) => decide.mutate({ decision, why })} />
      )}
    </>
  );
}
