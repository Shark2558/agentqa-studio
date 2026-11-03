import { MODES, money } from "../../lib/ai";
import type { WizardState } from "../../lib/wizard";

function aiSummary(s: WizardState): string {
  const title = MODES.find((m) => m.id === s.ai.mode)?.title ?? s.ai.mode;
  if (s.ai.mode === "none") return "No AI (rules only)";
  if (s.ai.mode === "local") return "Local AI: a model on this computer, nothing leaves your PC";
  const consent = s.ai.consent.send_text ? `text${s.ai.consent.send_screenshots ? " and screenshots" : ""} may be sent` : "no consent given yet, so no cloud call will be made";
  return `${title}: ${consent}; budget ${money(s.ai.budget.monthly_usd)} a month, warning at ${s.ai.budget.alert_at_pct} %`;
}

/** Step 6: what the agents will work with. */
export function StepReview({ s }: { s: WizardState }) {
  const readable = s.documents.filter((d) => d.status !== "unread");
  return (
    <dl className="review">
      <dt>Project</dt>
      <dd>
        <b>{s.name}</b> · <span className="mono">{s.url}</span> · {s.environment}
        {s.environment === "Production" && <span className="pill warn">read-only</span>}
      </dd>
      <dt>Requirements</dt>
      <dd>
        {readable.length > 0 && (
          <>
            {readable.length} document{readable.length === 1 ? "" : "s"}: {readable.map((d) => d.name).join(", ")}
            {s.documents.length > readable.length && <span className="muted"> ({s.documents.length - readable.length} could not be read and will be skipped)</span>}
          </>
        )}
        {readable.length > 0 && s.typed.trim() && <br />}
        {s.typed.trim() && (
          <>
            Typed text{s.chat ? ` — ${s.chat.items.length} requirement${s.chat.items.length === 1 ? "" : "s"} understood` : ""}
            {s.chat && !s.confirmed && <span className="pill warn">not confirmed yet</span>}
          </>
        )}
      </dd>
      <dt>Accounts</dt>
      <dd>{s.noLogin ? "No login needed" : s.roles.filter((r) => r.role.trim()).map((r) => `${r.role} (${r.login_option})`).join(", ")}</dd>
      <dt>AI mode</dt>
      <dd>{aiSummary(s)}</dd>
      <dt>Schedule</dt>
      <dd>None — start runs by hand</dd>
      <dt>Gates</dt>
      <dd>
        Approved automatically for this first run; the questions, test plan and defects the agents raise are kept for you to read in the old dashboard until M1.4
        brings them here.
      </dd>
    </dl>
  );
}
