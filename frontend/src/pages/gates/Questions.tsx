import { useCallback, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowsClockwise } from "@phosphor-icons/react";
import { useMe } from "../../App";
import { canWrite } from "../../lib/can";
import { errorWords, isStale, policyWords } from "../../lib/gates";
import { gatesApi, type Policy } from "../../lib/gatesApi";
import { useGateCounts, useRefreshWhenRunEnds } from "../../lib/useGateCounts";
import { Announce } from "../../components/gates/Announce";
import { QuestionCard } from "../../components/gates/QuestionCard";
import { GateTop } from "../../components/gates/GateTop";

type Tab = "open" | "answered";
const KEYS = ["questions", "changes"] as const;         // a re-plan rewrites the questions

/** What "Apply" does, in words: answers take effect only through a re-plan, which reuses the rule of the run that
 *  made the plan (the owner's decision, 4 Nov 2026), or project.yaml's when that run used it. */
function ApplyNote({ policy }: { policy: Policy }) {
  const whose = policy.source === "run" ? "the rule this plan was made with" : "this project's rule from project.yaml";
  return (
    <div className="notice info">
      <p>
        Answers take effect only when someone presses “Apply my answers and re-plan”. AgentQA then compares the requirements
        with the application again and designs the test plan again. It does not rewrite the requirements, so it costs nothing.
      </p>
      <p>Re-planning uses {whose}: {policyWords(policy)}.</p>
    </div>
  );
}

function useApply(slug: string, announce: (text: string) => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => gatesApi.applyAnswers(slug),
    onSuccess: () => {
      for (const key of ["gates", "runs", "live-sessions"]) queryClient.invalidateQueries({ queryKey: [key, slug] });
      announce("Re-planning started.");
    },
    onError: (e) => { if (isStale(e)) queryClient.invalidateQueries({ queryKey: ["gates", slug] }); },
  });
}

/** Gate 1: the Reconciler's questions, answered in plain English, then applied by a re-plan (compare and design). */
export function Questions() {
  const { slug = "" } = useParams();
  const [tab, setTab] = useState<Tab>("open");
  const [news, setNews] = useState("");
  const listHeading = useRef<HTMLHeadingElement>(null);
  const mayWrite = canWrite(useMe().data?.role);
  const view = useQuery({ queryKey: ["questions", slug, tab], queryFn: () => gatesApi.questions(slug, tab), placeholderData: keepPreviousData });
  const gates = useGateCounts(slug);
  useRefreshWhenRunEnds(slug, gates.data?.running, KEYS);
  const apply = useApply(slug, setNews);
  // A decided card leaves the list it was in: say what happened and keep focus on the list, not on the page's body.
  const onDone = useCallback((text: string) => { setNews(text); listHeading.current?.focus(); }, []);
  const counts = view.data?.counts;
  const running = gates.data?.running ?? false;
  const job = apply.data;
  const items = view.data?.items ?? [];

  return (
    <>
      <GateTop slug={slug} title="Questions" sub={counts ? `${counts.open} open · ${counts.answered} answered` : "Loading…"} />
      <Announce text={news} />
      {view.data && <ApplyNote policy={view.data.policy} />}
      {running && <p className="notice warn" role="status">A run is going: you can answer now, and apply your answers when it finishes.</p>}
      {mayWrite && (
        <div className="row gate-actions">
          <button type="button" className="btn primary" onClick={() => apply.mutate()} disabled={!counts?.answered || running || apply.isPending}
                  aria-describedby={counts?.answered ? undefined : "apply-hint"}>
            <ArrowsClockwise aria-hidden="true" />
            Apply my answers and re-plan
          </button>
          {!counts?.answered && <span id="apply-hint" className="small muted">Answer at least one question first.</span>}
        </div>
      )}
      {job && (
        <p className="notice ok">
          Re-planning started.{" "}
          <Link to={`/projects/${encodeURIComponent(slug)}/live?session=${encodeURIComponent(`job-${job.id}-${job.stage}`)}`}>
            Watch the re-plan in the Live View
          </Link>
        </p>
      )}
      {apply.error && <p className="notice bad" role="alert">{errorWords(apply.error)}</p>}
      <div className="filters" role="group" aria-label="Which questions">
        <button type="button" className="filter" aria-pressed={tab === "open"} onClick={() => setTab("open")}>Open ({counts?.open ?? 0})</button>
        <button type="button" className="filter" aria-pressed={tab === "answered"} onClick={() => setTab("answered")}>Answered ({counts?.answered ?? 0})</button>
      </div>
      <h2 ref={listHeading} tabIndex={-1} className="sr-only">{tab === "open" ? "Open questions" : "Answered questions"}</h2>
      {view.isError && <p className="notice bad" role="alert">The questions could not be loaded. Reload the page.</p>}
      {view.data && items.length === 0 && <p className="muted">{tab === "open" ? "No open questions." : "Nothing answered yet."}</p>}
      <div className="q-list">
        {items.map((q) => <QuestionCard key={q.id} slug={slug} question={q} mayWrite={mayWrite} onDone={onDone} />)}
      </div>
    </>
  );
}
