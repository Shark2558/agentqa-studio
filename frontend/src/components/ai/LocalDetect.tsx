import { hasKeyFor, type AiKey, type LocalRow } from "../../lib/ai";

type Props = {
  /** undefined while the probe runs. */
  rows: LocalRow[] | undefined;
  /** undefined while the keys load: "Use it" waits, so an already-stored server is never added twice. */
  keys: AiKey[] | undefined;
  onUse: (row: LocalRow) => void;
  busy: boolean;
};

/** The two fixed local addresses: running or not, the models listed, the fix in plain English, and "Use it". */
export function LocalDetect({ rows, keys, onUse, busy }: Props) {
  if (!rows) {
    return (
      <p className="muted small" role="status">
        Looking for Ollama and LM Studio on this computer…
      </p>
    );
  }
  return (
    <ul className="list local-list">
      {rows.map((r) => {
        const added = keys !== undefined && hasKeyFor(r, keys);
        const usable = keys !== undefined && r.running && r.model !== null;
        return (
          <li key={r.provider} className="list-row static">
            <span>
              <b>
                {r.name} <span className={`pill ${r.running ? "ok" : "neutral"}`}>{r.running ? "Running" : "Not running"}</span>
              </b>
              {r.models.length > 0 && <span className="small mono">{r.models.join(", ")}</span>}
              {r.fix && <span className="small muted">{r.fix}</span>}
            </span>
            {added ? (
              <span className="pill info">Added</span>
            ) : usable ? (
              <button type="button" className="btn sm" onClick={() => onUse(r)} disabled={busy}>
                Use it
              </button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
