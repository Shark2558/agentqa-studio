import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { errorWords } from "../../lib/gates";
import { gatesApi, type Disposition } from "../../lib/gatesApi";
import { ReasonDialog } from "./ReasonDialog";

/** The four statuses a person may give a requirement. "Covered" and "not covered" are computed by AgentQA and are
 *  never a person's claim, so they are not offered (FR-ONB-4). */
const DISPOSITIONS: readonly { id: Disposition; label: string }[] = [
  { id: "out_of_scope", label: "Out of scope" }, { id: "not_testable", label: "Not testable" },
  { id: "manual", label: "Tested by hand" }, { id: "clarify", label: "To clarify" },
];

/** Set one requirement's disposition, always with a reason: it replaces AgentQA's computed status. Choosing in the
 *  menu changes nothing by itself (arrow keys step through a closed menu, WCAG 3.2.2); "Set…" opens the reason. */
export function DispositionControl({ slug, rid }: { slug: string; rid: string }) {
  const queryClient = useQueryClient();
  const [choice, setChoice] = useState<Disposition | null>(null);
  const [asking, setAsking] = useState(false);
  const setButton = useRef<HTMLButtonElement>(null);
  const close = () => { setAsking(false); setButton.current?.focus(); };
  const set = useMutation({
    mutationFn: ({ disposition, why }: { disposition: Disposition; why: string }) => gatesApi.setDisposition(slug, rid, disposition, why),
    onSuccess: () => {
      setChoice(null);
      for (const key of ["requirements", "changes", "gates"]) queryClient.invalidateQueries({ queryKey: [key, slug] });
    },
  });
  const picked = DISPOSITIONS.find((d) => d.id === choice);
  return (
    <div className="disposition">
      <div className="row">
        <select aria-label={`New disposition for ${rid}`} value={choice ?? ""}
                onChange={(e) => setChoice(DISPOSITIONS.find((d) => d.id === e.target.value)?.id ?? null)}>
          <option value="">Change…</option>
          {DISPOSITIONS.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
        <button ref={setButton} type="button" className="btn sm" aria-label={`Set the disposition of ${rid}`} aria-expanded={asking}
                disabled={!picked || set.isPending} onClick={() => setAsking(true)}>
          Set…
        </button>
      </div>
      {picked && asking && (
        <ReasonDialog title={`Why is ${rid} “${picked.label}”?`} confirmLabel={`Set ${rid} to “${picked.label}”`} isRequired
                      isBusy={set.isPending} onConfirm={(why) => { close(); set.mutate({ disposition: picked.id, why }); }} onCancel={close} />
      )}
      {set.error && <p className="notice bad" role="alert">{errorWords(set.error)}</p>}
    </div>
  );
}
