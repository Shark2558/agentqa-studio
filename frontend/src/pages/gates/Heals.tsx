import { useCallback, useState } from "react";
import { useParams } from "react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMe } from "../../App";
import { canWrite } from "../../lib/can";
import { errorWords, isStale } from "../../lib/gates";
import { reviewApi, type HealDecision } from "../../lib/reviewApi";
import { useGateCounts, useRefreshWhenRunEnds } from "../../lib/useGateCounts";
import { Announce } from "../../components/gates/Announce";
import { GateTop } from "../../components/gates/GateTop";
import { HealCard } from "../../components/gates/HealCard";

const KEYS = ["heals", "changes"] as const;
const TABS: readonly { id: string | undefined; label: string }[] = [
  { id: undefined, label: "All" }, { id: "proposed", label: "To decide" }, { id: "approved", label: "Approved" }, { id: "rejected", label: "Rejected" },
];
const BY_HAND = /by hand/i;

type Decision = { id: number; decision: HealDecision; why: string };

/** The decision on a fix. `decide` keeps its identity from one render to the next (it hangs on the mutation's own stable
 *  `mutate`, not on the whole result, which is new every time), so the memoised cards are not drawn again for nothing. */
export function useHealDecision(slug: string, done: (text: string, warning: string) => void) {
  const queryClient = useQueryClient();
  const refresh = () => {
    for (const key of [...KEYS, "gates", "plan"]) queryClient.invalidateQueries({ queryKey: [key, slug] });
  };
  const { mutate, isPending, error } = useMutation({
    mutationFn: ({ id, decision, why }: Decision) => reviewApi.decideHeal(slug, id, decision, why),
    onSuccess: (r) => {
      refresh();
      const byHand = BY_HAND.test(r.note);
      done(`Fix ${r.id} ${r.status}${r.note && !byHand ? `: ${r.note}` : byHand ? ": project.yaml was not changed" : ""}.`, byHand ? r.note : "");
    },
    onError: (e) => { if (isStale(e)) refresh(); },
  });
  const decide = useCallback((id: number, decision: HealDecision, why: string) => mutate({ id, decision, why }), [mutate]);
  return { decide, isPending, error };
}

/** Heals: the Healer's proposed fixes for tests a changed screen broke, approved (no reason needed) or rejected with a
 *  reason. A workflow fix also writes project.yaml; when the engine could not, the page says to change it by hand. */
export function Heals() {
  const { slug = "" } = useParams();
  const mayWrite = canWrite(useMe().data?.role);
  const [status, setStatus] = useState<string | undefined>(undefined);
  const [news, setNews] = useState("");
  const [warning, setWarning] = useState("");
  const view = useQuery({ queryKey: ["heals", slug, status ?? ""], queryFn: () => reviewApi.heals(slug, status), placeholderData: keepPreviousData });
  const running = useGateCounts(slug).data?.running;
  useRefreshWhenRunEnds(slug, running, KEYS);
  const decision = useHealDecision(slug, (text, warn) => { setNews(text); setWarning(warn); });
  const v = view.data;
  const counts = v?.counts ?? {};
  const all = Object.values(counts).reduce((n, c) => n + c, 0);
  const proposed = counts.proposed ?? 0;
  return (
    <>
      <GateTop slug={slug} title="Heals" sub={v ? `${proposed} proposed fix${proposed === 1 ? "" : "es"} · ${all} in all` : "Loading…"} />
      <Announce text={news} />
      {view.isError && <p className="notice bad" role="alert">The fixes could not be loaded. Reload the page.</p>}
      {running && mayWrite && <p className="notice info">A run is going: decide on the fixes once it has finished.</p>}
      {warning && <p className="notice warn">{warning}</p>}
      <div className="filters" role="group" aria-label="Which fixes">
        {TABS.map((t) => (
          <button key={t.label} type="button" className="filter" aria-pressed={status === t.id} onClick={() => setStatus(t.id)}>
            {t.label} ({t.id ? counts[t.id] ?? 0 : all})
          </button>
        ))}
      </div>
      <h2 className="sr-only">Fixes</h2>
      {v && v.items.length === 0 && <p className="muted">No fixes here.</p>}
      {decision.error && <p className="notice bad" role="alert">{errorWords(decision.error)}</p>}
      <div className="defect-list">
        {v?.items.map((h) => <HealCard key={h.id} h={h} mayWrite={mayWrite} isBusy={decision.isPending || !!running} onDecide={decision.decide} />)}
      </div>
    </>
  );
}
