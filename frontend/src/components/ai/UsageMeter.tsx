import { capState, money, type Usage, type UsageRow } from "../../lib/ai";
import { ProgressBar } from "../ProgressBar";

type Props = {
  usage: Usage;
  /** Agent key to its name on the pages; unknown keys are shown as they are. */
  labels?: Record<string, string>;
};

const tokens = (r: UsageRow) => `${r.input_tokens.toLocaleString()} in · ${r.output_tokens.toLocaleString()} out`;

/** The month's spend against the cap: a banner at the warning and at the cap, the bar, then per agent and per run. */
export function UsageMeter({ usage, labels = {} }: Props) {
  const b = usage.budget;
  const cap = capState(b);
  return (
    <div className="meter">
      {cap.level === "warn" && (
        <p className="notice warn" role="status">
          {cap.text}
        </p>
      )}
      {cap.level === "bad" && (
        <p className="notice bad" role="alert">
          {cap.text}
        </p>
      )}
      <p className="meter-line">
        <b>{`${money(b.spent)} of ${money(b.cap)} used this month`}</b>
        <span className="muted small">{usage.calls} billed call{usage.calls === 1 ? "" : "s"} in {usage.month}</span>
      </p>
      <ProgressBar value={b.pct / 100} label="Monthly AI budget used" />
      {usage.calls === 0 && <p className="muted small">No AI call has cost anything this month.</p>}
      {usage.estimated && <p className="muted small">Some figures are estimated: a provider did not report its token counts, so the cost errs on the high side.</p>}
      {usage.agents.length > 0 && (
        <div className="scroll-x">
          <table aria-label="Spend per agent">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Calls</th>
                <th>Tokens</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {usage.agents.map((r) => (
                <tr key={r.agent}>
                  <td>{labels[r.agent ?? ""] ?? r.agent}</td>
                  <td className="mono">{r.calls}</td>
                  <td className="mono">{tokens(r)}</td>
                  <td className="mono">{money(r.cost_usd)}{r.estimated ? " (est.)" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {usage.runs.length > 0 && (
        <div className="scroll-x">
          <table aria-label="Spend per run">
            <thead>
              <tr>
                <th>Run</th>
                <th>Calls</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {usage.runs.map((r) => (
                <tr key={r.pipeline ?? "none"}>
                  <td className="mono">{r.pipeline ?? "outside a run"}</td>
                  <td className="mono">{r.calls}</td>
                  <td className="mono">{money(r.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">Costs use the providers' prices as of {usage.prices_dated}.</p>
    </div>
  );
}
