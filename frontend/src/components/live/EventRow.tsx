import { memo } from "react";
import { XCircle } from "@phosphor-icons/react";
import type { LiveEvent } from "../../lib/api";

const TIME = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** One line of the stream. A failure is marked by a glyph and the word, never by colour alone. */
export const EventRow = memo(function EventRow({ event }: { event: LiveEvent }) {
  const bad = event.level === "bad";
  return (
    <div className={`evt${bad ? " fail" : ""}`}>
      <div className="k" title={event.agent}>
        {event.agent}
      </div>
      <div>
        <p>
          {event.title}
          {bad && (
            <span className="pill bad">
              <XCircle aria-hidden="true" />
              Failed
            </span>
          )}
        </p>
        <div className="t">
          {TIME.format(new Date(event.t * 1000))} · {event.kind}
        </div>
      </div>
    </div>
  );
});
