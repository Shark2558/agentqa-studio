import { CalendarBlank, Robot } from "@phosphor-icons/react";

/** Steps 4 and 5 are shown so the owner sees the whole journey; their controls arrive with M1.2 and M1.5. */
export function StepAi() {
  return (
    <div className="choices">
      <label className="choice selected" aria-label="No AI, selected for this project">
        <input type="radio" name="ai" checked readOnly />
        <span>
          <b>No AI</b>
          <span className="muted small">Documents are read, the application explored and tests written by rules. Free, private, works offline. Selected for this project.</span>
        </span>
      </label>
      <div className="choice disabled" aria-disabled="true">
        <Robot aria-hidden="true" />
        <span>
          <b>Local AI</b> <span className="pill neutral">coming in M1.2</span>
          <span className="muted small">A model on this machine (Ollama or LM Studio) helps read vague documents and write better test ideas. Nothing leaves your PC.</span>
        </span>
      </div>
      <div className="choice disabled" aria-disabled="true">
        <Robot aria-hidden="true" />
        <span>
          <b>Cloud AI</b> <span className="pill neutral">coming in M1.2</span>
          <span className="muted small">Anthropic, Google or OpenAI with your own key, a monthly budget and consent switches. Falls back to No AI at the cap.</span>
        </span>
      </div>
    </div>
  );
}

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
