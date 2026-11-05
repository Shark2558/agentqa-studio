import { useId, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LOG_SHOWN, answer, command, commandWords, movesFocus, type Command, type ScreenBox, type Waiting } from "../../lib/assist";
import { errorWords, isStale } from "../../lib/gates";
import { reviewApi, reviewFiles } from "../../lib/reviewApi";
import { useAnswered } from "../../lib/useAssist";
import { Modal } from "./Modal";
import { ScreenShot } from "./ScreenShot";
import { GotoBox, KeyButtons, SpotChips, TypeBox, type Send } from "./TakeOverParts";

type Props = { slug: string; item: Waiting; onMinimise: () => void };

/** The box the person chose to type into (none until they choose one), and whether they asked to see what they type. */
type Target = { box: ScreenBox | null; reveal: boolean };
const NO_TARGET: Target = { box: null, reveal: false };

/** Commands go one at a time, in the order they were given (a second waits for the first's answer), and the text of
 *  one is not kept by the request cache once it is taken. `sent` is the last one taken, in words. */
function useTakeOver(slug: string, id: number) {
  const queryClient = useQueryClient();
  const answered = useAnswered(slug);
  const [sent, setSent] = useState("");
  const refresh = () => {
    for (const key of ["assist", "gates"]) queryClient.invalidateQueries({ queryKey: [key, slug] });
  };
  const send = useMutation({
    scope: { id: `takeover-${slug}-${id}` },
    mutationFn: (c: Command) => reviewApi.command(slug, id, c),
    gcTime: 0,
    onSuccess: (_, c) => {
      setSent(commandWords(c));
      void queryClient.invalidateQueries({ queryKey: ["assist", slug] });
    },
    onError: (e) => { if (isStale(e)) refresh(); },
  });
  const finish = useMutation({
    mutationFn: (done: boolean) => reviewApi.answer(slug, id, done ? answer.done() : answer.skip()),
    gcTime: 0,
    onSuccess: answered,
    onError: (e) => { if (isStale(e)) refresh(); },
  });
  return { send, finish, sent };
}

/** The box chosen to type into, and the commands as the person gives them: each one is refused outright while the
 *  production tick is missing, and one that may have moved the cursor drops the choice of box (and the wish to see). */
function useCommands(send: ReturnType<typeof useTakeOver>["send"], locked: boolean) {
  const [target, setTarget] = useState<Target>(NO_TARGET);
  const run: Send = async (c, picked) => {
    if (locked) return false;                                   // the tick is checked here too, whatever called
    setTarget((now) => (picked ? { box: picked, reveal: false } : movesFocus(c) ? NO_TARGET : now));
    try {
      await send.mutateAsync(c, { onSuccess: () => send.reset() });
      return true;
    } catch {
      return false;                                             // the error is shown below
    }
  };
  const reveal = (on: boolean) => setTarget((now) => ({ ...now, reveal: on }));
  return { target, run, reveal };
}

function ActionLog({ lines }: { lines: readonly string[] }) {
  if (!lines.length) return null;
  return (
    <>
      <p className="small-heading">What you did</p>
      <ol className="assist-log" aria-label="What you did">{lines.slice(-LOG_SHOWN).map((line, i) => <li key={`${i}-${line}`}>{line}</li>)}</ol>
    </>
  );
}

function ProductionWarning({ id, isUnderstood, onUnderstand }: { id: string; isUnderstood: boolean; onUnderstand: (on: boolean) => void }) {
  return (
    <div id={id} className="notice bad">
      <p><b>This is the live production application.</b> What you click and type here really happens there.</p>
      <label className="check">
        <input type="checkbox" checked={isUnderstood} onChange={(e) => onUnderstand(e.target.checked)} /> I understand
      </label>
    </div>
  );
}

/** The person drives the agent's browser (fills the screen): the live screenshot (a click on it is a click there),
 *  the boxes and buttons on it, a box to type into, the keys, an address on the portal, the last six actions, and
 *  Continue / Cancel. On a production application nothing is sent before the "I understand" tick (decision 6). */
export function TakeOver({ slug, item, onMinimise }: Props) {
  const { send, finish, sent } = useTakeOver(slug, item.id);
  const [understood, setUnderstood] = useState(false);
  const warning = useId();
  const chips = useId();
  const locked = item.production && !understood;
  const disabled = locked || finish.isPending;
  const { target, run, reveal } = useCommands(send, locked);
  const title = `You have the ${item.agent || "agent"}'s browser${item.role ? ` (as ${item.role})` : ""}`;
  const error = send.error ?? finish.error;
  return (
    <Modal label={title} className="takeover" describedBy={item.production ? warning : undefined} onEscape={onMinimise}>
      <div className="assist-head">
        <h2 className="assist-q">{title}</h2>
        <button type="button" className="btn sm" onClick={onMinimise}>Minimise</button>
      </div>
      {item.question && <p className="small assist-hint">{item.question}</p>}
      {item.hint && <p className="small muted assist-hint">{item.hint}</p>}
      {item.production && <ProductionWarning id={warning} isUnderstood={understood} onUnderstand={setUnderstood} />}
      {item.headed && <p className="notice info small">The browser window is also open on this computer: you can use it there directly.</p>}
      <div className="takeover-grid">
        <div>
          {item.url && <p className="mono small assist-url">{item.url}</p>}
          <ScreenShot src={reviewFiles.shot(slug, item.id, item.shotV)} vw={item.vw} vh={item.vh} hasShot={item.hasShot}
                      label={`The ${item.agent || "agent"}'s screen`} isDisabled={disabled || send.isPending}
                      describedBy={`${chips}-boxes ${chips}-buttons`} onPoint={(p) => { void run(command.click(p)); }} />
        </div>
        <div className="takeover-controls">
          <SpotChips idBase={chips} fields={item.fields} clickables={item.clickables} isDisabled={disabled} onSend={run} />
          <TypeBox box={target.box} reveal={target.reveal} isDisabled={disabled} onSend={run} onReveal={reveal} />
          <KeyButtons isDisabled={disabled} onSend={run} />
          <GotoBox isDisabled={disabled} onSend={run} />
          <ActionLog lines={item.log} />
        </div>
      </div>
      <p role="status" aria-label="Take-over news" className={sent ? "small muted" : "sr-only"}>{sent}</p>
      {error && <p className="notice bad" role="alert">{errorWords(error)}</p>}
      <div className="row assist-foot">
        <button type="button" className="btn sm primary" disabled={finish.isPending} onClick={() => finish.mutate(true)}>Continue: I&apos;m done</button>
        <button type="button" className="btn sm" disabled={finish.isPending} onClick={() => finish.mutate(false)}>Cancel</button>
      </div>
    </Modal>
  );
}
