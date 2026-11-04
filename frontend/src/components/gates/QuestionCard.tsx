import { useId, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { errorWords, isStale, when } from "../../lib/gates";
import { gatesApi, type Question } from "../../lib/gatesApi";
import { WhyButton } from "./ReasonDialog";

const VALUE_MAX = 400;
const KIND_WORDS: Readonly<Record<string, string>> = {
  divergence: "The requirements and the application disagree",
  srs_only_field: "A field in the requirements was not found on any screen",
  srs_only_feature: "A feature in the requirements was not found",
  srs_only_screen: "A screen in the requirements was not found",
  app_only: "Found in the application, not in the requirements",
  ambiguous: "A vague requirement",
  inferred_access: "Who may open a page",
  workflow: "A workflow between roles",
};
const kindWords = (kind: string) => (Object.hasOwn(KIND_WORDS, kind) ? KIND_WORDS[kind] : kind);

type Props = { slug: string; question: Question; mayWrite: boolean; onDone?: (message: string) => void };

/** One question from the Reconciler. Its text comes from the requirements and the application: shown as text only.
 *  The value box appears only for an option that asks for one (`needs_value`). Save stays enabled and says what is
 *  missing, so nobody faces a dead button. `onDone` tells the page, which announces it and keeps focus. */
export function QuestionCard({ slug, question: q, mayWrite, onDone }: Props) {
  const id = useId();
  const queryClient = useQueryClient();
  const [choice, setChoice] = useState<number | null>(null);
  const [value, setValue] = useState("");
  const [missing, setMissing] = useState<string | null>(null);
  const chosen = choice === null ? null : q.options[choice];
  const needsValue = !!chosen?.needs_value;
  const refresh = (message: string) => {
    for (const key of ["questions", "gates", "changes"]) queryClient.invalidateQueries({ queryKey: [key, slug] });
    onDone?.(message);
  };
  // "Someone already answered" and the like mean this card is out of date: reload the list it came from.
  const onError = (e: unknown) => { if (isStale(e)) queryClient.invalidateQueries({ queryKey: ["questions", slug] }); };
  const answer = useMutation({
    mutationFn: () => gatesApi.answer(slug, q.id, choice ?? 0, needsValue ? value.trim() : ""),
    onSuccess: () => refresh("Answer saved."),
    onError,
  });
  const reopen = useMutation({ mutationFn: (why: string) => gatesApi.reopen(slug, q.id, why), onSuccess: () => refresh("Question reopened."), onError });
  const error = answer.error ?? reopen.error;
  const open = q.status === "open";
  const save = () => {
    const problem = choice === null ? "Choose one of the options first." : needsValue && !value.trim() ? "Enter the value this option asks for." : null;
    setMissing(problem);
    reopen.reset();
    if (!problem) answer.mutate();
  };

  return (
    <article className="card q-card" aria-labelledby={`${id}-q`}>
      <div className="q-meta small">
        {q.priority && <span className={`pill ${q.priority === "High" ? "bad" : "neutral"}`}>{q.priority}</span>}
        {q.req_id && <span className="mono">{q.req_id}</span>}
        <span className="muted">{kindWords(q.kind)}</span>
      </div>
      <p className="q-text" id={`${id}-q`}>{q.question}</p>
      {q.proposed && <p className="small muted">AgentQA suggests: {q.proposed}</p>}
      {q.note_only && (
        <p className="small muted" id={`${id}-note`}>
          {mayWrite ? "Your answer" : "An answer to this question"} is kept as a note for checking by hand: re-planning does
          not change the automated tests for it yet.
        </p>
      )}
      {open && mayWrite && (
        <form noValidate onSubmit={(e) => { e.preventDefault(); save(); }}>
          <div role="radiogroup" aria-labelledby={`${id}-q`} aria-describedby={q.note_only ? `${id}-note` : undefined} className="choices q-options">
            {q.options.map((o, i) => (
              <label key={o.label} className={`choice${choice === i ? " selected" : ""}`}>
                <input type="radio" name={`${id}-choice`} checked={choice === i} onChange={() => { setChoice(i); setMissing(null); }} />
                <span>{o.label}</span>
              </label>
            ))}
          </div>
          {needsValue && (
            <label className="q-value">
              Your value (this option asks for one)
              <input type="text" required maxLength={VALUE_MAX} value={value} onChange={(e) => setValue(e.target.value)}
                     aria-describedby={missing ? `${id}-missing` : undefined} />
            </label>
          )}
          {missing && <p id={`${id}-missing`} className="small bad-text" role="alert">{missing}</p>}
          <div className="row-end">
            <button type="submit" className="btn primary" disabled={answer.isPending} aria-describedby={`${id}-q`}>Save answer</button>
          </div>
        </form>
      )}
      {open && !mayWrite && (
        <ul className="q-readonly small">{q.options.map((o) => <li key={o.label}>{o.label}</li>)}</ul>
      )}
      {!open && (
        <div className="q-answer">
          <p className="small">Answer: <b>{q.answer ?? "—"}</b>{q.value && <> — <span className="mono">{q.value}</span></>}</p>
          <p className="small muted">Answered {when(q.answered_at)}</p>
          {mayWrite && (
            <WhyButton label="Reopen" name={`Reopen question ${q.id}`} title="Reopen this question: why?" confirmLabel="Reopen the question"
                       isBusy={reopen.isPending} onConfirm={(why) => { answer.reset(); reopen.mutate(why); }} />
          )}
        </div>
      )}
      {error ? <p className="notice bad" role="alert">{errorWords(error)}</p> : null}
    </article>
  );
}
