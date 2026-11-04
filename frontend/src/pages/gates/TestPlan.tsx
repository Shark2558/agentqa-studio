import { useCallback, useState } from "react";
import { useParams } from "react-router";
import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DownloadSimple } from "@phosphor-icons/react";
import { useMe } from "../../App";
import { canWrite } from "../../lib/can";
import { errorWords, isStale, needsWhy, setMany, toggle, type Selection } from "../../lib/gates";
import { gateFiles, gatesApi, type CaseDecision, type PlanView } from "../../lib/gatesApi";
import { useGateCounts, useRefreshWhenRunEnds } from "../../lib/useGateCounts";
import { Announce } from "../../components/gates/Announce";
import { CaseTable, type CaseFilter } from "../../components/gates/CaseTable";
import { DecisionBar, type BarAction } from "../../components/gates/DecisionBar";
import { GateTop } from "../../components/gates/GateTop";
import { PlanApproval } from "../../components/gates/PlanApproval";
import { PlanSummary } from "../../components/gates/PlanSummary";
import { TypeTable } from "../../components/gates/TypeTable";

const NONE: Selection = new Set();
const PLAN_KEYS = ["plan", "plan-cases", "changes"] as const;
const CHUNK = 500;                     // the API takes at most 500 ids per decision (CASES_MAX)
const CASE_ACTIONS: readonly BarAction<CaseDecision>[] = [
  { decision: "approve", label: "Approve", verb: "Approve", needsWhy: needsWhy("cases", "approve"), isPrimary: true },
  { decision: "reject", label: "Reject", verb: "Reject", needsWhy: needsWhy("cases", "reject") },
  { decision: "reset", label: "Back to review", verb: "Undo the decision on", needsWhy: needsWhy("cases", "reset") },
];
const DONE: Readonly<Record<CaseDecision, string>> = { approve: "Approved", reject: "Rejected", reset: "Undid the decision on" };
const cases = (n: number) => `${n} case${n === 1 ? "" : "s"}`;

function chunks<T>(items: readonly T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

/** The plan's decisions: per case (the selection), per type, and the ready imported cases. Only the newest refusal
 *  is shown; one that says the page is out of date reloads it. */
function usePlanDecisions(slug: string, announce: (text: string) => void, clear: () => void) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  const refresh = () => { for (const key of [...PLAN_KEYS, "gates"]) queryClient.invalidateQueries({ queryKey: [key, slug] }); };
  const handlers = { onMutate: () => setError(null), onError: (e: unknown) => { setError(e); if (isStale(e)) refresh(); } };
  const byCase = useMutation({
    mutationFn: async ({ ids, decision, why }: { ids: string[]; decision: CaseDecision; why: string }) => {
      for (const part of chunks(ids, CHUNK)) await gatesApi.decideCases(slug, part, decision, why);
      return ids.length;
    },
    ...handlers,
    onSuccess: (n, { decision }) => { clear(); refresh(); announce(`${DONE[decision]} ${cases(n)}.`); },
  });
  const byType = useMutation({
    mutationFn: ({ ctype, decision, why }: { ctype: string; decision: "approve" | "reject"; why: string }) => gatesApi.decideType(slug, ctype, decision, why),
    ...handlers,
    onSuccess: (_, { ctype, decision }) => { refresh(); announce(`${decision === "approve" ? "Approved" : "Rejected"} every ${ctype} case.`); },
  });
  const imported = useMutation({
    mutationFn: () => gatesApi.decideImported(slug, [], "approve_ready", ""),
    ...handlers,
    onSuccess: (r) => { refresh(); announce(`Approved ${r.changed} imported case${r.changed === 1 ? "" : "s"}.`); },
  });
  return { byCase, byType, imported, busy: byCase.isPending || byType.isPending || imported.isPending, error };
}

function useCaseList(slug: string, filter: CaseFilter) {
  return useInfiniteQuery({
    queryKey: ["plan-cases", slug, filter.type ?? "", filter.status ?? ""],
    queryFn: ({ pageParam }) => gatesApi.cases(slug, { ...filter, offset: pageParam }),
    initialPageParam: 0,
    placeholderData: keepPreviousData,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
  });
}

function subline(v: PlanView | undefined): string {
  if (!v) return "Loading…";
  if (!v.plan.summary) return "no test plan yet";
  return `${cases(v.plan.summary.cases)} · ${v.plan.approved ? "approved" : "waiting for your approval"}`;
}

/** Gate 2: review the test plan, decide its cases, approve it, download it, and continue the run. */
export function TestPlan() {
  const { slug = "" } = useParams();
  const mayWrite = canWrite(useMe().data?.role);
  const [filter, setFilter] = useState<CaseFilter>({});
  const [selected, setSelected] = useState<Selection>(NONE);
  const [news, setNews] = useState("");
  const view = useQuery({ queryKey: ["plan", slug], queryFn: () => gatesApi.plan(slug) });
  const gates = useGateCounts(slug);
  useRefreshWhenRunEnds(slug, gates.data?.running, PLAN_KEYS);
  const list = useCaseList(slug, filter);
  const decide = usePlanDecisions(slug, setNews, () => setSelected(NONE));
  const onToggle = useCallback((id: string) => setSelected((s) => toggle(s, id)), []);
  const onToggleAll = useCallback((ids: readonly string[], on: boolean) => setSelected((s) => setMany(s, ids, on)), []);
  const rows = list.data?.pages.flatMap((p) => p.items) ?? [];
  const v = view.data;
  const running = gates.data?.running ?? v?.running ?? false;       // the polled counts: a finished run frees the page
  const busy = running || decide.busy;

  return (
    <>
      <GateTop slug={slug} title="Test plan" sub={subline(v)}>
        <a className="btn" href={gateFiles.testCases(slug)} download>
          <DownloadSimple aria-hidden="true" />
          Download the test cases (Excel)
        </a>
      </GateTop>
      <Announce text={news} />
      {view.isError && <p className="notice bad" role="alert">The test plan could not be loaded. Reload the page.</p>}
      {running && <p className="notice warn" role="status">A run is going: decisions wait until it finishes.</p>}
      {v && (
        <>
          <PlanSummary view={v} slug={slug} mayWrite={mayWrite} isBusy={busy} onApproveImported={() => decide.imported.mutate()} />
          <PlanApproval slug={slug} plan={v.plan} running={running} mayWrite={mayWrite} toReview={v.types.reduce((n, t) => n + t.proposed, 0)}
                        onApproved={setNews} />
          <section className="card flat mt-4" aria-labelledby="h-cases">
            <h2 id="h-cases">Cases</h2>
            <TypeTable types={v.types} mayWrite={mayWrite} isBusy={busy} onDecide={(ctype, decision, why) => decide.byType.mutate({ ctype, decision, why })} />
            <CaseTable types={v.types} cases={rows} filter={filter} onFilter={(next) => { setFilter(next); setSelected(NONE); }} selected={selected}
                       mayWrite={mayWrite} onToggle={onToggle} onToggleAll={onToggleAll} />
            {list.isError && <p className="notice bad" role="alert">The cases could not be loaded. Reload the page.</p>}
            {list.isSuccess && rows.length === 0 && <p className="muted">No cases match these filters.</p>}
            {list.hasNextPage && (
              <button type="button" className="btn" disabled={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>Show more</button>
            )}
            {decide.error !== null && <p className="notice bad" role="alert">{errorWords(decide.error)}</p>}
            {mayWrite && (
              <DecisionBar count={selected.size} noun={["case", "cases"]} actions={CASE_ACTIONS} isBusy={busy} onClear={() => setSelected(NONE)}
                           onDecide={(decision, why) => decide.byCase.mutate({ ids: [...selected], decision, why })} />
            )}
          </section>
        </>
      )}
    </>
  );
}
