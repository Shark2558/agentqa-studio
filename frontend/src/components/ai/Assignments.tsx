/* eslint-disable jsx-a11y/no-redundant-roles, jsx-a11y/no-interactive-element-to-noninteractive-role -- the explicit table roles are
   deliberate: under 760 px the CSS stacks each row as a block, which strips the implicit roles (styles/ai.css). */
import { TIER_IDS, TIER_LABELS, isTier, routeLabel, type CatalogAgent, type EffectiveRow, type Tier } from "../../lib/ai";

type Props = {
  agents: CatalogAgent[];
  assignments: Record<string, Tier>;
  effective: EffectiveRow[];
  /** Provider id to its name. */
  names: Record<string, string>;
  onChange: (agent: string, tier: Tier | null) => void;
  /** True while the form holds unsaved changes: the right-hand column then describes the saved state. */
  stale: boolean;
};

/** Per agent: the tier it may use (or the default), and which provider and model would answer it today. */
export function Assignments({ agents, assignments, effective, names, onChange, stale }: Props) {
  const rows = new Map(effective.map((r) => [r.agent, r]));
  return (
    <>
      <p className="muted small">
        Each agent asks for a tier, never a model: cheap for small jobs, balanced for most, strong for writing requirements, vision for images. The provider order below decides who answers.
        {stale && " Save to see which model would answer with these changes."}
      </p>
      {/* Explicit table roles: on phones the CSS stacks each row into a card (display: block drops the implicit roles). */}
      <table className="assign" role="table" aria-label="Which model answers each agent">
        <thead role="rowgroup">
          <tr role="row">
            <th role="columnheader">Agent</th>
            <th role="columnheader">Tier</th>
            <th role="columnheader">Answered by</th>
          </tr>
        </thead>
        <tbody role="rowgroup">
          {agents.map((a) => {
            const row = rows.get(a.agent);
            const chosen = assignments[a.agent] ?? "";
            return (
              <tr key={a.agent} role="row">
                <td role="cell" className="wrap agent-name">{a.label}</td>
                <td role="cell" data-label="Tier">
                  <select aria-label={`Tier for ${a.label}`} value={chosen} onChange={(e) => onChange(a.agent, isTier(e.target.value) ? e.target.value : null)}>
                    <option value="">Default ({isTier(a.tier) ? TIER_LABELS[a.tier] : a.tier})</option>
                    {TIER_IDS.map((t) => (
                      <option key={t} value={t}>
                        {TIER_LABELS[t]}
                      </option>
                    ))}
                  </select>
                </td>
                <td role="cell" data-label="Answered by" className={`wrap${row?.reason ? " muted" : ""}`}>
                  {row ? routeLabel(row, names) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}
