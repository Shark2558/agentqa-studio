import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Cloud, Desktop } from "@phosphor-icons/react";
import { aiApi, cloudKeyCount, localKeyToAdd, localSummary, type AiSettingsInput } from "../../lib/ai";
import { ModeForm } from "../../components/ai/ModeForm";

type Props = {
  slug: string;
  ai: AiSettingsInput;
  onChange: (ai: AiSettingsInput) => void;
};

/** Step 4: the AI mode for this project, with an honest line on what is actually available right now. */
export function StepAi({ slug, ai, onChange }: Props) {
  const local = useQuery({ queryKey: ["ai", "local"], queryFn: aiApi.local });
  const keys = useQuery({ queryKey: ["ai", "keys"], queryFn: aiApi.keys });
  const wantsLocal = ai.mode === "local" || ai.mode === "hybrid";
  const willAdd = wantsLocal && local.data && keys.data && localKeyToAdd(local.data, keys.data) !== null;
  const localLine = local.isPending
    ? "Looking for Ollama and LM Studio on this computer…"
    : local.isError
      ? "Could not check for a local model right now."
      : `${localSummary(local.data).text}${willAdd ? " · it is added to your keys when you continue" : ""}`;
  const count = keys.data ? cloudKeyCount(keys.data) : null;
  const cloudLine = keys.isPending ? "Checking the cloud keys…" : keys.isError ? "Could not load the cloud keys right now." : count === 0 ? "No cloud key yet" : `${count} cloud key${count === 1 ? "" : "s"} set up`;
  return (
    <>
      <ModeForm value={ai} onChange={onChange} />
      <ul className="ai-status" aria-label="What is available on this computer">
        <li>
          <Desktop aria-hidden="true" />
          {localLine}
        </li>
        <li>
          <Cloud aria-hidden="true" />
          {cloudLine} ·{" "}
          <Link to={`/projects/${encodeURIComponent(slug)}/ai`} target="_blank" rel="noopener noreferrer">
            AI providers (opens in a new tab)
          </Link>
        </li>
      </ul>
    </>
  );
}
