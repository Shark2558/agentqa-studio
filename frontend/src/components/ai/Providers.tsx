import type { AiKey, Catalog, Policy } from "../../lib/ai";
import { KeyForm } from "./KeyForm";
import { KeyRow } from "./KeyRow";
import { ProviderOrder } from "./ProviderOrder";

type Props = {
  keys: AiKey[];
  catalog: Catalog;
  policy: Policy;
};

/** Stored keys (masked), the add form, and the provider order. Keys are shared by every project on this computer. */
export function Providers({ keys, catalog, policy }: Props) {
  const names = Object.fromEntries(catalog.providers.map((p) => [p.id, p.name]));
  return (
    <>
      <p className="muted small">
        Keys live in the encrypted vault on this computer and serve every project; the app shows only their first and last four characters. A local server added from the panel above appears here too.
      </p>
      {keys.length === 0 ? (
        <p className="muted">No key yet. Add one below, or press “Use it” on a running local server.</p>
      ) : (
        <ul className="list keys">
          {keys.map((k) => (
            <KeyRow key={k.id} k={k} providerName={names[k.provider] ?? k.provider} />
          ))}
        </ul>
      )}
      <KeyForm catalog={catalog} />
      <ProviderOrder policy={policy} names={names} />
    </>
  );
}
