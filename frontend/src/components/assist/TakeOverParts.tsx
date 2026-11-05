import { useId, useState } from "react";
import { NO_TEXT, command, isSecretBox, portalPath, type Command, type ScreenBox, type Spot } from "../../lib/assist";

/** Sends a command and says whether the server took it. `picked` is the box a click on its chip selects. */
export type Send = (c: Command, picked?: ScreenBox) => Promise<boolean>;

export const TYPE_LABEL = "Type into the selected box";

/** The boxes and buttons on the agent's screen: a click on one is a click at its place (and a box becomes the one
 *  typed into). Their words come from the tested site: text only. The lists carry ids (`<idBase>-boxes`,
 *  `<idBase>-buttons`) so the screenshot can say it is described by them. */
export function SpotChips({ idBase, fields, clickables, isDisabled, onSend }: {
  idBase: string; fields: readonly ScreenBox[]; clickables: readonly Spot[]; isDisabled: boolean; onSend: Send;
}) {
  return (
    <>
      {fields.length > 0 && (
        <ul id={`${idBase}-boxes`} className="assist-chips" aria-label="Boxes on the screen">
          {fields.map((f, i) => {
            const name = f.label || f.type || NO_TEXT;
            return (
              <li key={`${i}-${f.label}`}>
                <button type="button" className="chip-btn" aria-label={`Box on the screen: ${name}${f.filled ? " (filled)" : ""}`} disabled={isDisabled}
                        onClick={() => { void onSend(command.click(f), f); }}>
                  {name}{f.filled ? " ✓" : ""}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {clickables.length > 0 && (
        <ul id={`${idBase}-buttons`} className="assist-chips" aria-label="Buttons on the screen">
          {clickables.map((c, i) => (
            <li key={`${i}-${c.text}`}>
              <button type="button" className="chip-btn" aria-label={`Button on the screen: ${c.text || NO_TEXT}`} disabled={isDisabled}
                      onClick={() => { void onSend(command.click(c)); }}>{c.text || NO_TEXT}</button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

type TypeBoxProps = { box: ScreenBox | null; reveal: boolean; isDisabled: boolean; onReveal: (on: boolean) => void; onSend: Send };

/** "Type into the selected box": what is typed is hidden (password-style, and sent as a secret) unless the person ticks
 *  "Show what I type" (never offered for a password box). Only the box that was chosen is known, not where the cursor
 *  is now, so the wish to see is dropped whenever the cursor may have moved. What was typed is cleared once it is
 *  sent and taken (the server keeps only its length once the agent has typed it), and kept when it is refused. */
export function TypeBox({ box, reveal, isDisabled, onReveal, onSend }: TypeBoxProps) {
  const id = useId();
  const [value, setValue] = useState("");
  const secretBox = isSecretBox(box);
  const hidden = !reveal || secretBox;
  const submit = async () => {
    const typed = value;
    if (!typed) return;
    if (await onSend(command.type(typed, { hide: !reveal, box }))) setValue((now) => (now === typed ? "" : now));
  };
  return (
    <form className="assist-answer" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <label htmlFor={id}>{TYPE_LABEL}</label>
      {box && <span className="small muted assist-selected"> (selected: {box.label || box.type || NO_TEXT})</span>}
      <div className="row">
        <input id={id} type={hidden ? "password" : "text"} autoComplete={hidden ? "new-password" : "off"} spellCheck={false}
               autoCapitalize="off" maxLength={500} value={value} disabled={isDisabled} onChange={(e) => setValue(e.target.value)} />
        <button type="submit" className="btn sm primary" disabled={isDisabled || !value}>Type it</button>
      </div>
      <label className="check">
        <input type="checkbox" checked={!hidden} disabled={secretBox} onChange={(e) => onReveal(e.target.checked)} /> Show what I type
      </label>
    </form>
  );
}

const KEY_BUTTONS: readonly { label: string; cmd: Command }[] = [
  { label: "Enter", cmd: command.press("Enter") }, { label: "Tab", cmd: command.press("Tab") },
  { label: "Backspace", cmd: command.press("Backspace") }, { label: "Back", cmd: command.back() },
  { label: "Scroll down", cmd: command.scroll() }, { label: "Scroll up", cmd: command.scrollUp() },
];

export function KeyButtons({ isDisabled, onSend }: { isDisabled: boolean; onSend: Send }) {
  return (
    <div className="row assist-keys" role="group" aria-label="Keys">
      {KEY_BUTTONS.map((k) => (
        <button key={k.label} type="button" className="btn sm" disabled={isDisabled} onClick={() => { void onSend(k.cmd); }}>{k.label}</button>
      ))}
    </div>
  );
}

/** "Open an address on the portal": only a path of the portal under test ("/apply"); the server checks its scope. The
 *  address is cleared once it is taken, and kept when it is refused. */
export function GotoBox({ isDisabled, onSend }: { isDisabled: boolean; onSend: Send }) {
  const id = useId();
  const [value, setValue] = useState("");
  const path = portalPath(value);
  const submit = async () => {
    const typed = value;
    if (path && (await onSend(command.goto(path)))) setValue((now) => (now === typed ? "" : now));
  };
  return (
    <form className="assist-answer" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <label htmlFor={id}>Open an address on the portal</label>
      <div className="row">
        <input id={id} type="text" placeholder="/apply" autoComplete="off" spellCheck={false} autoCapitalize="off" maxLength={400}
               value={value} disabled={isDisabled} onChange={(e) => setValue(e.target.value)} />
        <button type="submit" className="btn sm" disabled={isDisabled || !path}>Open</button>
      </div>
    </form>
  );
}
