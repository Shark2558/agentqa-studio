import { useRef } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, Play } from "@phosphor-icons/react";
import { api } from "../../lib/api";
import { errorWords, isStale, when } from "../../lib/gates";
import { gatesApi, type PlanState } from "../../lib/gatesApi";

type Props = { slug: string; plan: PlanState; running: boolean; mayWrite: boolean; toReview: number; onApproved: (text: string) => void };

/** Approve the plan the person is looking at (its fingerprint), then "Generate and run" continues the pipeline. The
 *  Approve button disappears once it worked, so focus moves to this section's heading and the page announces it. */
export function PlanApproval({ slug, plan, running, mayWrite, toReview, onApproved }: Props) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const heading = useRef<HTMLHeadingElement>(null);
  const refresh = () => {
    for (const key of ["plan", "plan-cases", "gates", "changes"]) queryClient.invalidateQueries({ queryKey: [key, slug] });
  };
  const approve = useMutation({
    mutationFn: (digest: string) => gatesApi.approvePlan(slug, digest, ""),
    onSuccess: () => { refresh(); onApproved("The test plan is approved."); heading.current?.focus(); },
    onError: (e) => { if (isStale(e)) refresh(); },
  });
  const start = useMutation({
    mutationFn: () => api.startRun(slug, { scope: "continue" }),
    onSuccess: (run) => {
      for (const key of ["runs", "live-sessions", "gates"]) queryClient.invalidateQueries({ queryKey: [key, slug] });
      navigate(`/projects/${encodeURIComponent(slug)}/live?session=${encodeURIComponent(`job-${run.id}-${run.stage}`)}`);
    },
  });
  const error = approve.error ?? start.error;

  if (!plan.summary) return <p className="notice warn">There is no test plan yet: run the pipeline as far as the plan first.</p>;
  return (
    <section className="card flat mt-4 approval" aria-labelledby="h-approval">
      <h2 id="h-approval" ref={heading} tabIndex={-1}>Approval</h2>
      {plan.approved ? (
        <>
          <p className="notice ok"><CheckCircle aria-hidden="true" /> Approved on {when(plan.approved_at)}.</p>
          {mayWrite && (
            <div className="row">
              <button type="button" className="btn primary" disabled={running || start.isPending} onClick={() => start.mutate()}>
                <Play aria-hidden="true" />
                Generate and run
              </button>
              <span className="small muted">AgentQA writes the tests for the approved cases and runs them.</span>
            </div>
          )}
        </>
      ) : mayWrite ? (
        <>
          <p className="small">
            Approving the plan also approves the {toReview} case{toReview === 1 ? "" : "s"} still to review. Rejected cases stay out.
          </p>
          <button type="button" className="btn primary" disabled={running || approve.isPending || !plan.digest}
                  onClick={() => plan.digest && approve.mutate(plan.digest)}>
            Approve the test plan
          </button>
        </>
      ) : (
        <p className="small muted">The plan waits for the owner or a tester to approve it.</p>
      )}
      {error && <p className="notice bad" role="alert">{errorWords(error)}</p>}
    </section>
  );
}
