import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "@phosphor-icons/react";
import { aiApi, errorText, needsAddress, type Catalog, type KeyInput } from "../../lib/ai";

type Props = {
  catalog: Catalog;
};

const EMPTY: KeyInput = { provider: "", label: "", key: "", base_url: "", model: "" };

/** Add a key: a password box that is emptied the moment the save finishes, stored or not; the address only for
 *  providers without one; nothing the browser may remember or autocomplete. */
export function KeyForm({ catalog }: Props) {
  const queryClient = useQueryClient();
  const providers = catalog.providers;
  const [form, setForm] = useState<KeyInput>({ ...EMPTY, provider: providers[0]?.id ?? "" });
  const provider = providers.find((p) => p.id === form.provider);
  const wantsAddress = provider ? needsAddress(provider) : false;
  const keyless = provider?.keyless === true;
  const add = useMutation({
    mutationFn: () => {
      const body: KeyInput = { provider: form.provider, label: form.label.trim(), key: keyless ? "" : form.key };
      if (wantsAddress && form.base_url?.trim()) body.base_url = form.base_url.trim();
      if (form.model?.trim()) body.model = form.model.trim();
      return aiApi.addKey(body);
    },
    onSuccess: () => {
      setForm((f) => ({ ...f, label: "", base_url: "", model: "" }));
      queryClient.invalidateQueries({ queryKey: ["ai", "keys"] });
    },
    onSettled: () => setForm((f) => ({ ...f, key: "" })),
  });
  const set = (patch: Partial<KeyInput>) => {
    add.reset();                                                   // a new edit retires the old "stored" or error line
    setForm((f) => ({ ...f, ...patch }));
  };
  const chooseProvider = (id: string) => set({ provider: id, key: "" });   // a typed secret never carries over to another provider
  const canAdd = form.provider && form.label.trim() && (form.key || keyless) && (!wantsAddress || form.base_url?.trim());

  return (
    <form
      className="key-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (canAdd) add.mutate();
      }}
    >
      <h3>Add a key</h3>
      <div className="grid g-keyform">
        <div>
          <label htmlFor="key-provider">Provider</label>
          <select id="key-provider" value={form.provider} onChange={(e) => chooseProvider(e.target.value)}>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="key-label">Name</label>
          <input id="key-label" value={form.label} maxLength={80} placeholder="Work account" autoComplete="off" onChange={(e) => set({ label: e.target.value })} />
        </div>
        <div>
          <label htmlFor="key-secret">API key</label>
          <input id="key-secret" type="password" autoComplete="new-password" spellCheck={false} autoCapitalize="off" value={form.key} maxLength={512} onChange={(e) => set({ key: e.target.value })} disabled={keyless} />
        </div>
        {wantsAddress && (
          <div>
            <label htmlFor="key-url">Service address</label>
            <input id="key-url" type="url" inputMode="url" autoComplete="off" value={form.base_url ?? ""} placeholder="https://" onChange={(e) => set({ base_url: e.target.value })} />
          </div>
        )}
        <div>
          <label htmlFor="key-model">Model (optional)</label>
          <input id="key-model" value={form.model ?? ""} autoComplete="off" placeholder="auto: the best model for each tier" onChange={(e) => set({ model: e.target.value })} />
        </div>
      </div>
      <p className="muted small">
        {keyless ? "This provider needs no key: the address is enough." : "Type the key yourself; it is stored in the encrypted vault and never shown again."} Nothing is sent to the provider until a project with Cloud or Hybrid AI runs.
        {!canAdd && " A provider, a name" + (keyless ? "" : " and the key") + (wantsAddress ? " and the service address" : "") + " are needed."}
      </p>
      {add.isError && (
        <p className="notice bad" role="alert">
          {errorText(add.error, "The key could not be saved; try again")}
        </p>
      )}
      {add.isSuccess && (
        <p className="notice ok" role="status">
          Key stored. Press Test to check it answers.
        </p>
      )}
      <div className="row-end">
        <button className="btn primary" type="submit" disabled={!canAdd || add.isPending}>
          <Plus aria-hidden="true" />
          {add.isPending ? "Saving…" : "Add key"}
        </button>
      </div>
    </form>
  );
}
