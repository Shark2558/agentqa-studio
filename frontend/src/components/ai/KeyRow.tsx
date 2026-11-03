import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash } from "@phosphor-icons/react";
import { aiApi, errorText, type AiKey, type KeyTest } from "../../lib/ai";

type Props = {
  k: AiKey;
  providerName: string;
};

/** The gateway's key states (agentqa.ai.store / router) in the owner's words; unknown kinds are shown as a warning. */
const HEALTH: Record<string, { cls: string; text: string }> = {
  untested: { cls: "neutral", text: "Not tested yet" },
  ok: { cls: "ok", text: "Working" },
  cooling: { cls: "warn", text: "Resting after an error" },
  model: { cls: "bad", text: "Model not available" },
  invalid_key: { cls: "bad", text: "Key rejected" },
  billing: { cls: "bad", text: "Billing problem" },
};

function health(k: AiKey): { cls: string; text: string } {
  if (k.status === "disabled") return { cls: "neutral", text: "Disabled" };
  const state = k.state?.state ?? "untested";
  return HEALTH[state] ?? { cls: "warn", text: state.replace(/_/g, " ") };
}

function outcome(t: KeyTest): string {
  if (t.ok) return `OK · ${t.model ?? "model found"}${t.ms ? ` · ${t.ms} ms` : ""}`;
  return `Failed: ${t.detail}`;
}

const GENERIC = "Something went wrong; try again";

/** One stored key: masked, with its provider, health, and the Test / Disable / Delete actions. The secret never comes
 *  back; every failed action says so; a test result is dropped once the key is changed again. */
export function KeyRow({ k, providerName }: Props) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["ai", "keys"] });
  const [result, setResult] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const begin = () => {
    setResult(null);
    setProblem(null);
  };
  const test = useMutation({ mutationFn: () => aiApi.testKey(k.id), onMutate: begin, onSuccess: (t) => setResult(outcome(t)), onError: (e) => setProblem(errorText(e, GENERIC)), onSettled: refresh });
  const toggle = useMutation({ mutationFn: () => aiApi.patchKey(k.id, { status: k.status === "active" ? "disabled" : "active" }), onMutate: begin, onSuccess: refresh, onError: (e) => setProblem(errorText(e, GENERIC)) });
  const remove = useMutation({
    mutationFn: () => aiApi.deleteKey(k.id),
    onMutate: begin,
    onSuccess: () => {
      refresh();
      document.getElementById("h-providers")?.focus();            // the row is gone: focus lands on the section, not nowhere
    },
    onError: (e) => setProblem(errorText(e, GENERIC)),
  });
  const h = health(k);
  const busy = test.isPending || toggle.isPending || remove.isPending;

  function confirmDelete() {
    if (window.confirm(`Delete the key “${k.label}”? Projects using ${providerName} will lose it.`)) remove.mutate();
  }

  return (
    <li className="list-row static key-row">
      <span>
        <b>{k.label}</b>
        <span className="small">
          {providerName} · <span className="mono">{k.masked}</span> · <span className={`pill ${k.scope === "local" ? "info" : "neutral"}`}>{k.scope}</span>{" "}
          <span className={`pill ${h.cls}`}>{h.text}</span>
        </span>
        {k.state?.last_error && k.status === "active" && h.cls === "bad" && <span className="small muted">{k.state.last_error}</span>}
        {result && (
          <span className="small" role="status">
            {result}
          </span>
        )}
        {problem && (
          <span className="small bad-text" role="alert">
            {problem}
          </span>
        )}
      </span>
      <span className="key-actions">
        <button type="button" className="btn sm" aria-label={`Test ${k.label}`} onClick={() => test.mutate()} disabled={busy}>
          {test.isPending ? "Testing…" : "Test"}
        </button>
        <button type="button" className="btn sm" aria-label={`${k.status === "active" ? "Disable" : "Enable"} ${k.label}`} onClick={() => toggle.mutate()} disabled={busy}>
          {k.status === "active" ? "Disable" : "Enable"}
        </button>
        <button type="button" className="btn sm" aria-label={`Delete ${k.label}`} onClick={confirmDelete} disabled={busy}>
          <Trash aria-hidden="true" />
          Delete
        </button>
      </span>
    </li>
  );
}
