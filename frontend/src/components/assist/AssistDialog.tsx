import { useId, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { NO_TEXT, answer, takes, whoWaits, type Answer, type Waiting } from "../../lib/assist";
import { errorWords, isStale } from "../../lib/gates";
import { reviewApi, reviewFiles } from "../../lib/reviewApi";
import { useAnswered } from "../../lib/useAssist";
import { Modal } from "./Modal";
import { ScreenShot } from "./ScreenShot";

type Props = { slug: string; item: Waiting; onMinimise: () => void };

/** Answering sends one answer; once it is taken the lists ask again and the dialog closes with the question. A refusal
 *  that means "out of date" (someone answered first, it ran out of time) reloads them too. What was typed is not kept
 *  by the request cache once it is sent. */
function useAnswer(slug: string, id: number) {
  const queryClient = useQueryClient();
  const answered = useAnswered(slug);
  return useMutation({
    mutationFn: (body: Answer) => reviewApi.answer(slug, id, body),
    gcTime: 0,
    onSuccess: answered,
    onError: (e) => {
      if (isStale(e)) for (const key of ["assist", "gates"]) queryClient.invalidateQueries({ queryKey: [key, slug] });
    },
  });
}

function TextAnswer({ item, isBusy, onSend }: { item: Waiting; isBusy: boolean; onSend: (text: string) => void }) {
  const id = useId();
  const [value, setValue] = useState("");
  const otp = item.kind === "otp";
  const secret = item.secret && !otp;
  const text = value.trim() ? value : "";                 // what is sent keeps every space; only an empty answer is refused
  return (
    <form className="assist-answer" onSubmit={(e) => { e.preventDefault(); if (text) onSend(text); }}>
      <label htmlFor={id}>Your answer</label>
      <div className="row">
        <input id={id} type={secret ? "password" : "text"} inputMode={otp ? "numeric" : undefined}
               autoComplete={otp ? "one-time-code" : secret ? "new-password" : "off"} spellCheck={false} autoCapitalize="off"
               maxLength={200} value={value} onChange={(e) => setValue(e.target.value)} />
        <button type="submit" className="btn sm primary" disabled={isBusy || !text}>Send</button>
      </div>
    </form>
  );
}

type ChoicesProps = { idBase: string; item: Waiting; isBusy: boolean; onAnswer: (a: Answer) => void };

function Choices({ idBase, item, isBusy, onAnswer }: ChoicesProps) {
  return (
    <>
      {takes(item.kind, "option") && item.options.length > 0 && (
        <ul className="assist-chips" aria-label="Choices">
          {item.options.map((o, i) => (
            <li key={`${i}-${o}`}><button type="button" className="chip-btn" disabled={isBusy} onClick={() => onAnswer(answer.option(i))}>{o || NO_TEXT}</button></li>
          ))}
        </ul>
      )}
      {takes(item.kind, "point") && item.clickables.length > 0 && (
        <>
          <p className="small-heading">On the screen:</p>
          <ul id={`${idBase}-buttons`} className="assist-chips" aria-label="Buttons on the screen">
            {item.clickables.map((c, i) => (
              <li key={`${i}-${c.text}`}>
                <button type="button" className="chip-btn" aria-label={`On the screen: ${c.text || NO_TEXT}`} disabled={isBusy}
                        onClick={() => onAnswer(answer.point(c, c.text))}>{c.text || NO_TEXT}</button>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

/** A question from an agent that is stuck: its screen as it is now (a click on it answers a "where do I click?"),
 *  the choices, the buttons on the screen, a box for a typed answer (a one-time code with the number keypad), "Let
 *  me take over" and "I can't help: skip it". Escape only minimises it. Yes and No are offered only when the question
 *  has no choices of its own. */
export function AssistDialog({ slug, item, onMinimise }: Props) {
  const idBase = useId();
  const send = useAnswer(slug, item.id);
  const busy = send.isPending;
  const onAnswer = (a: Answer) => send.mutate(a, { onSuccess: () => send.reset() });
  return (
    <Modal label={item.question || "AgentQA needs you"} className="assist-dialog" onEscape={onMinimise}>
      <div className="assist-head">
        <p className="assist-who">{whoWaits(item)}</p>
        <button type="button" className="btn sm" onClick={onMinimise}>Minimise</button>
      </div>
      <h2 className="assist-q">{item.question}</h2>
      {item.hint && <p className="small assist-hint">{item.hint}</p>}
      {item.url && <p className="mono small assist-url">{item.url}</p>}
      <ScreenShot src={reviewFiles.shot(slug, item.id, item.shotV)} vw={item.vw} vh={item.vh} hasShot={item.hasShot}
                  label={`${whoWaits(item)}'s screen`} isDisabled={busy} describedBy={`${idBase}-buttons`}
                  onPoint={takes(item.kind, "point") ? (p) => onAnswer(answer.point(p)) : undefined} />
      <Choices idBase={idBase} item={item} isBusy={busy} onAnswer={onAnswer} />
      {takes(item.kind, "ok") && item.options.length === 0 && (
        <div className="row">
          <button type="button" className="btn sm primary" disabled={busy} onClick={() => onAnswer(answer.ok(true))}>Yes</button>
          <button type="button" className="btn sm" disabled={busy} onClick={() => onAnswer(answer.ok(false))}>No</button>
        </div>
      )}
      {takes(item.kind, "text") && <TextAnswer item={item} isBusy={busy} onSend={(t) => onAnswer(answer.text(t))} />}
      {send.error && <p className="notice bad" role="alert">{errorWords(send.error)}</p>}
      <div className="row assist-foot">
        {takes(item.kind, "takeover") && (
          <button type="button" className="btn sm" disabled={busy} onClick={() => onAnswer(answer.takeover())}>Let me take over</button>
        )}
        <button type="button" className="btn sm" disabled={busy} onClick={() => onAnswer(answer.skip())}>I can&apos;t help: skip it</button>
      </div>
    </Modal>
  );
}
