import { useEffect, useRef } from "react";
import { FloppyDisk } from "@phosphor-icons/react";
import { errorText, type AiSettingsInput, type Catalog, type EffectiveRow, type Tier } from "../../lib/ai";
import { ModeForm } from "./ModeForm";
import { Assignments } from "./Assignments";

type SaveState = {
  isPending: boolean;
  isError: boolean;
  isSuccess: boolean;
  error: unknown;
};

type Props = {
  value: AiSettingsInput;
  /** True when the form differs from what is saved. */
  dirty: boolean;
  catalog: Catalog | undefined;
  catalogFailed: boolean;
  effective: EffectiveRow[];
  names: Record<string, string>;
  save: SaveState;
  onChange: (next: AiSettingsInput) => void;
  onAssignment: (agent: string, tier: Tier | null) => void;
  onSubmit: () => void;
};

/** The one form on the AI page: mode, consent, budget and the per-agent tiers, saved together. */
export function AiForm({ value, dirty, catalog, catalogFailed, effective, names, save, onChange, onAssignment, onSubmit }: Props) {
  const savedLine = useRef<HTMLParagraphElement>(null);
  const showSaved = save.isSuccess && !dirty;
  useEffect(() => {
    if (showSaved) savedLine.current?.focus();                       // the Save button has just disabled itself under the keyboard
  }, [showSaved]);

  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <section className="card" aria-labelledby="h-mode">
        <h2 id="h-mode">Mode, consent and budget</h2>
        <ModeForm value={value} onChange={onChange} />
      </section>
      <section className="card" aria-labelledby="h-agents">
        <h2 id="h-agents">Agents</h2>
        {catalog ? (
          <Assignments agents={catalog.agents} assignments={value.assignments} effective={effective} names={names} onChange={onAssignment} stale={dirty} />
        ) : catalogFailed ? (
          <p className="notice bad">The agent list could not be loaded. Reload the page to try again.</p>
        ) : (
          <p className="muted">Loading the agent list…</p>
        )}
        {save.isError && (
          <p className="notice bad" role="alert">
            {errorText(save.error, "The settings could not be saved; try again")}
          </p>
        )}
        {showSaved && (
          <p className="notice ok" role="status" tabIndex={-1} ref={savedLine}>
            Saved. The table shows which model now answers each agent.
          </p>
        )}
        <div className="row-end">
          <button className="btn primary" type="submit" disabled={!dirty || save.isPending}>
            <FloppyDisk aria-hidden="true" />
            {save.isPending ? "Saving…" : "Save AI settings"}
          </button>
        </div>
      </section>
    </form>
  );
}
