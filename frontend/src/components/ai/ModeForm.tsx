import type { ReactNode } from "react";
import { Cloud, Desktop, Robot, ShieldCheck } from "@phosphor-icons/react";
import { MODES, type AiMode, type AiSettingsInput } from "../../lib/ai";

type Props = {
  value: AiSettingsInput;
  onChange: (next: AiSettingsInput) => void;
  /** The radio group's name; two forms on one page need different names. */
  name?: string;
};

const ICONS: Record<AiMode, ReactNode> = {
  none: <ShieldCheck aria-hidden="true" />,
  local: <Desktop aria-hidden="true" />,
  cloud: <Cloud aria-hidden="true" />,
  hybrid: <Robot aria-hidden="true" />,
};
const BUDGET_MIN = 0.5;
const BUDGET_MAX = 1000;
const NO_CONSENT = { send_text: false, send_screenshots: false };
const usesCloud = (mode: AiMode) => mode === "cloud" || mode === "hybrid";

/** The AI mode with its consent switches and budget; consent and budget only matter when text may leave this PC.
 *  Leaving the cloud forgets the consent, so a later switch back never carries an unseen "yes". */
export function ModeForm({ value, onChange, name = "ai-mode" }: Props) {
  const cloudy = usesCloud(value.mode);
  const choose = (mode: AiMode) => onChange({ ...value, mode, consent: usesCloud(mode) ? value.consent : NO_CONSENT });
  return (
    <>
      <div className="choices" role="radiogroup" aria-label="AI mode">
        {MODES.map((m) => (
          <label key={m.id} className={`choice${value.mode === m.id ? " selected" : ""}`}>
            <input type="radio" name={name} value={m.id} checked={value.mode === m.id} onChange={() => choose(m.id)} aria-labelledby={`${name}-${m.id}-title`} aria-describedby={`${name}-${m.id}-blurb`} />
            {ICONS[m.id]}
            <span>
              <b id={`${name}-${m.id}-title`}>{m.title}</b>
              <span className="muted small" id={`${name}-${m.id}-blurb`}>
                {m.blurb}
              </span>
            </span>
          </label>
        ))}
      </div>
      {cloudy && <ConsentFields value={value} onChange={onChange} name={name} />}
      {cloudy && <BudgetFields value={value} onChange={onChange} name={name} />}
    </>
  );
}

function ConsentFields({ value, onChange, name }: Required<Props>) {
  const { consent } = value;
  const set = (patch: Partial<AiSettingsInput["consent"]>) => onChange({ ...value, consent: { ...consent, ...patch } });
  const fallback = value.mode === "hybrid" ? "Local AI" : "No AI";
  return (
    <fieldset className="ai-fieldset">
      <legend>Consent: what may leave this computer</legend>
      <label className="check">
        <input type="checkbox" checked={consent.send_text} onChange={(e) => set({ send_text: e.target.checked })} id={`${name}-text`} />
        Allow text from your documents and the application's pages to be sent to the cloud provider
      </label>
      <label className="check">
        <input type="checkbox" checked={consent.send_screenshots} onChange={(e) => set({ send_screenshots: e.target.checked })} id={`${name}-shots`} />
        Allow screenshots to be sent too (Visual QA and reading scanned documents need this)
      </label>
      {!consent.send_text && (
        <p className="notice warn">
          Without the text consent no cloud call is made: this project behaves like {fallback} until you tick the first box. Personal data such as mobile numbers and emails is masked before anything is sent.
        </p>
      )}
    </fieldset>
  );
}

function BudgetFields({ value, onChange, name }: Required<Props>) {
  const { budget } = value;
  const setNumber = (field: keyof AiSettingsInput["budget"], raw: string) => {
    const n = Number(raw);
    if (raw.trim() !== "" && Number.isFinite(n)) onChange({ ...value, budget: { ...budget, [field]: n } });   // an emptied box is not "0"
  };
  return (
    <div className="grid g-budget">
      <div>
        <label htmlFor={`${name}-budget`}>Monthly budget (USD)</label>
        <input id={`${name}-budget`} type="number" inputMode="decimal" min={BUDGET_MIN} max={BUDGET_MAX} step={0.01} value={budget.monthly_usd} onChange={(e) => setNumber("monthly_usd", e.target.value)} />
      </div>
      <div>
        <label htmlFor={`${name}-alert`}>Warn me at (% of budget)</label>
        <input id={`${name}-alert`} type="number" inputMode="numeric" min={1} max={100} step={1} value={budget.alert_at_pct} onChange={(e) => setNumber("alert_at_pct", e.target.value)} />
      </div>
      <p className="muted small g-span">
        At the cap, Cloud AI stops calling out and the run continues as No AI; Hybrid keeps using the free local model. Spend is counted from the providers' token figures and today's prices.
      </p>
    </div>
  );
}
