import { errorText, type AiKey, type LocalRow } from "../../lib/ai";
import { LocalDetect } from "./LocalDetect";

type Props = {
  rows: LocalRow[] | undefined;
  probeFailed: boolean;
  keys: AiKey[] | undefined;
  keysFailed: boolean;
  onUse: (row: LocalRow) => void;
  busy: boolean;
  addError: unknown;
};

/** The "Local AI on this computer" card: the probe's rows, or why they are missing, and what "Use it" did. */
export function LocalCard({ rows, probeFailed, keys, keysFailed, onUse, busy, addError }: Props) {
  return (
    <section className="card" aria-labelledby="h-local">
      <h2 id="h-local" tabIndex={-1}>
        Local AI on this computer
      </h2>
      {probeFailed ? (
        <p className="notice bad">Could not check for a local model. Reload the page to try again.</p>
      ) : keysFailed ? (
        <p className="notice bad">The stored keys could not be loaded, so a local server cannot be added right now.</p>
      ) : (
        <LocalDetect rows={rows} keys={keys} onUse={onUse} busy={busy} />
      )}
      {addError !== null && addError !== undefined && (
        <p className="notice bad" role="alert">
          {errorText(addError, "The local server could not be added; try again")}
        </p>
      )}
    </section>
  );
}
