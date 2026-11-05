import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pause, Play } from "@phosphor-icons/react";
import type { Paused } from "../../lib/assist";
import { errorWords } from "../../lib/gates";
import { reviewApi } from "../../lib/reviewApi";

type Props = { slug: string; paused: Paused | undefined; running: boolean };

export const PAUSE_WORDS = "Agents with a browser stop at their next step and hand it to you; the Writer, Designer, Triage and Reporter carry on.";
const PAUSED_NEWS = "Paused: agents with a browser stop at their next step and hand it to you.";
const RESUMED_NEWS = "Resumed: the agents carry on.";

/** "Pause and take over" while a run goes, "Paused: resume all" while the agents are paused (fact 10: only the
 *  agents with a browser stop). Resume also hands back every browser still held. While a press is on its way the
 *  button is marked `aria-disabled` and ignores clicks, instead of being disabled, so the focus stays on it; what
 *  happened is said in a status line. */
export function PauseButton({ slug, paused, running }: Props) {
  const queryClient = useQueryClient();
  const [news, setNews] = useState("");
  const on = !!paused?.on;
  const act = useMutation({
    mutationFn: (pausing: boolean) => (pausing ? reviewApi.pause(slug) : reviewApi.resume(slug)),
    onSuccess: (_, pausing) => setNews(pausing ? PAUSED_NEWS : RESUMED_NEWS),
    onSettled: () => {
      for (const key of ["assist", "gates"]) queryClient.invalidateQueries({ queryKey: [key, slug] });
    },
  });
  if (!running && !on) return null;
  return (
    <div className="pause">
      <button type="button" className={`btn sm${on ? " primary" : ""}`} aria-disabled={act.isPending} onClick={() => { if (!act.isPending) act.mutate(!on); }}>
        {on ? <Play aria-hidden="true" /> : <Pause aria-hidden="true" />}
        {on ? "Paused: resume all" : "Pause and take over"}
      </button>
      <p className="small muted">{on && paused?.by ? `Paused by ${paused.by}. ` : ""}{PAUSE_WORDS}</p>
      <p role="status" aria-label="Pause news" className={news ? "small" : "sr-only"}>{news}</p>
      {act.error && <p className="notice bad small" role="alert">{errorWords(act.error)}</p>}
    </div>
  );
}
