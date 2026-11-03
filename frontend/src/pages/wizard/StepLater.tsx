import { CalendarBlank } from "@phosphor-icons/react";

/** Step 5 is shown so the owner sees the whole journey; its controls arrive with M1.5. */
export function StepSchedule() {
  return (
    <div className="choices">
      <div className="choice disabled" aria-disabled="true">
        <CalendarBlank aria-hidden="true" />
        <span>
          <b>Repeat this run</b> <span className="pill neutral">coming in M1.5</span>
          <span className="muted small">Daily, weekly or a custom timetable, plus a webhook your build pipeline can call. Until then, start runs from the project page.</span>
        </span>
      </div>
    </div>
  );
}
