import { useMe } from "../../App";
import { whoWaits } from "../../lib/assist";
import { canWrite } from "../../lib/can";
import { openAssist, useAssist } from "../../lib/useAssist";

/** The Live View's "AgentQA needs you" while an agent waits: who waits, and a button that opens the question in the
 *  help box (the dock owns the dialog). A Viewer reads that AgentQA waits for the owner or a tester. */
export function NeedsYouBanner({ slug }: { slug: string }) {
  const mayDrive = canWrite(useMe().data?.role);
  const items = useAssist(slug).data?.items ?? [];
  const first = items[0];
  if (!first) return null;
  const more = items.length > 1 ? ` (and ${items.length - 1} more)` : "";
  return (
    <section className="notice warn row needs-banner" aria-label="AgentQA needs you">
      <p>
        <b>AgentQA needs you:</b>{" "}
        {mayDrive ? `${whoWaits(first)} is waiting for you${more}.` : `AgentQA is waiting for the owner or a tester (${whoWaits(first)}).`}
      </p>
      {mayDrive && (
        <button type="button" className="btn sm primary" onClick={() => openAssist(slug, first.id)}>
          {first.kind === "takeover" ? "Take over the browser" : "Open the question"}
        </button>
      )}
    </section>
  );
}
