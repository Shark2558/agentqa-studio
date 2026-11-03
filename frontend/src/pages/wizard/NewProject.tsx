import { useEffect, useReducer, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, Play } from "@phosphor-icons/react";
import { ApiError, api } from "../../lib/api";
import { STEPS, answersForApi, canContinue, initialWizard, reduceWizard, rolesForApi } from "../../lib/wizard";
import { StepBasics } from "./StepBasics";
import { StepRequirements } from "./StepRequirements";
import { StepAccounts } from "./StepAccounts";
import { StepAi, StepSchedule } from "./StepLater";
import { StepReview } from "./StepReview";

/** The six-step new-project wizard (PRD §4). The project exists from step 1 on, so every later step saves into it. */
export function NewProject() {
  const [s, dispatch] = useReducer(reduceWizard, initialWizard);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const step = STEPS[s.step];
  const heading = useRef<HTMLHeadingElement>(null);
  const firstStep = useRef(true);
  useEffect(() => {                                     // a new step: move focus to its heading so the change is announced
    if (firstStep.current) firstStep.current = false;
    else heading.current?.focus();
  }, [s.step]);

  const advance = useMutation({
    mutationFn: async () => {
      if (step.key === "basics" && !s.slug) {
        const project = await api.createProject(s.name.trim(), s.url.trim(), s.environment);
        dispatch({ type: "created", slug: project.slug });
        queryClient.invalidateQueries({ queryKey: ["projects"] });
      }
      if (step.key === "requirements" && s.slug && s.typed.trim() && !s.confirmed) {
        await api.typedRequirements(s.slug, s.typed, answersForApi(s), (s.chat?.items ?? []).map((i) => i.text));
      }
      if (step.key === "accounts" && s.slug) {
        await api.saveAccounts(s.slug, { no_login: s.noLogin, roles: rolesForApi(s) });
      }
    },
    onSuccess: () => {
      setError(null);
      dispatch({ type: "next" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Something went wrong; try again"),
  });

  const start = useMutation({
    mutationFn: () => api.startRun(s.slug!, { scope: "pipeline", policy: "srs_wins", auto_approve: true }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${encodeURIComponent(s.slug!)}/live?session=job-${run.id}-${run.stage}`);
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "The run did not start"),
  });

  return (
    <>
      <div className="topbar">
        <div>
          <div className="crumbs">
            <Link to="/">Projects</Link> / <b>New project</b>
          </div>
          <h1>New project</h1>
        </div>
      </div>
      <div className="wizard">
        <ol className="steps" aria-label="Steps">
          {STEPS.map((st, i) => (
            <li key={st.key} className={i === s.step ? "current" : i < s.step ? "done" : ""} aria-current={i === s.step ? "step" : undefined}>
              {i < s.step ? (
                <button type="button" className="step-link" onClick={() => dispatch({ type: "goto", step: i })}>
                  <span className="num">
                    <Check aria-hidden="true" />
                  </span>
                  <span className="title">{st.title}</span>
                </button>
              ) : (
                <span>
                  <span className="num">{i + 1}</span>
                  <span className="title">{st.title}</span>
                </span>
              )}
            </li>
          ))}
        </ol>

        <form
          className="card step"
          onSubmit={(e) => {
            e.preventDefault();
            if (step.key === "review") start.mutate();
            else advance.mutate();
          }}
        >
          <h2 ref={heading} tabIndex={-1}>
            Step {s.step + 1} of {STEPS.length}: {step.title}
          </h2>
          <p className="why">
            <b>Why we ask.</b> {step.why}
          </p>

          {step.key === "basics" && (
            <StepBasics
              name={s.name}
              url={s.url}
              environment={s.environment}
              locked={s.slug !== null}
              onField={(field, value) => dispatch({ type: "field", field, value })}
              onEnvironment={(value) => dispatch({ type: "field", field: "environment", value })}
            />
          )}
          {step.key === "requirements" && s.slug && (
            <StepRequirements
              slug={s.slug}
              documents={s.documents}
              typed={s.typed}
              chat={s.chat}
              answers={s.answers}
              confirmed={s.confirmed}
              onDocument={(doc) => dispatch({ type: "document", doc })}
              onRemoveDocument={(name) => dispatch({ type: "removeDocument", name })}
              onTyped={(value) => dispatch({ type: "field", field: "typed", value })}
              onChat={(chat) => dispatch({ type: "chat", chat })}
              onAnswer={(id, answer) => dispatch({ type: "answer", id, answer })}
              onConfirm={() => dispatch({ type: "confirm" })}
            />
          )}
          {step.key === "accounts" && (
            <StepAccounts
              noLogin={s.noLogin}
              roles={s.roles}
              onNoLogin={(value) => dispatch({ type: "field", field: "noLogin", value })}
              onRole={(index, role) => dispatch({ type: "role", index, role })}
              onAdd={() => dispatch({ type: "addRole" })}
              onRemove={(index) => dispatch({ type: "removeRole", index })}
            />
          )}
          {step.key === "ai" && <StepAi />}
          {step.key === "schedule" && <StepSchedule />}
          {step.key === "review" && <StepReview s={s} />}

          {error && (
            <p className="notice bad" role="alert">
              {error}
            </p>
          )}
          <div className="wizard-nav">
            <button className="btn" type="button" onClick={() => dispatch({ type: "back" })} disabled={s.step === 0 || advance.isPending}>
              <ArrowLeft aria-hidden="true" />
              Back
            </button>
            <span className="spacer" />
            {step.key === "review" ? (
              <button className="btn primary" type="submit" disabled={start.isPending || !s.slug}>
                <Play aria-hidden="true" />
                {start.isPending ? "Starting…" : "Run full pipeline"}
              </button>
            ) : (
              <button className="btn primary" type="submit" disabled={!canContinue(s) || advance.isPending}>
                {advance.isPending ? "Saving…" : step.key === "schedule" ? "Skip for now" : "Continue"}
                <ArrowRight aria-hidden="true" />
              </button>
            )}
          </div>
        </form>
      </div>
    </>
  );
}
