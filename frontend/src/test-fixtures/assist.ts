/** What the help box's API answers (M1.4 Phase C), shaped as `orchestrator/gates/helpbox.py` sends it, plus a visual
 *  review and heals list like the ones `routes_review.py` sends for the demo. */
import type { Paused } from "../lib/assist";
import type { HealsView, VisualView } from "../lib/reviewApi";

export type RawWaiting = Record<string, unknown>;

/** A waiting question as the owner or a tester receives it. */
export function waiting(over: RawWaiting = {}): RawWaiting {
  return {
    id: 7, kind: "navigate", role: "citizen", agent: "explorer", at: "2026-11-05T10:00:00",
    question: "Which button logs me in as a citizen?", hint: "Click it on the screen, or choose below.",
    options: ["Citizen Login", "Department Login"], clickables: [{ text: "Citizen Login", x: 640, y: 212 }, { text: "Help", x: 40, y: 20 }],
    fields: [], secret: false, url: "http://127.0.0.1:8800/", vw: 1280, vh: 800, headed: false, log: [], shot_v: 3, has_shot: true,
    production: false, ...over,
  };
}

/** A take-over: the person drives the agent's browser. */
export function takeover(over: RawWaiting = {}): RawWaiting {
  return waiting({
    id: 9, kind: "takeover", question: "Log in as citizen for me", options: [], hint: "Click, type and press keys here.",
    clickables: [{ text: "Get OTP", x: 700, y: 400 }],
    fields: [{ label: "Registered number", type: "tel", x: 600, y: 300, filled: false },
             { label: "Password", type: "password", x: 600, y: 360, filled: false }],
    log: ["Clicked at (1, 1)", "Clicked at (2, 2)", "Typed '98'", "Pressed Enter", "Went back", "Scrolled", "Opened /apply"],
    ...over,
  });
}

/** What a Viewer receives: who is waiting, never the screen. */
export function watched(over: RawWaiting = {}): RawWaiting {
  return { id: 7, kind: "navigate", role: "citizen", agent: "explorer", at: "2026-11-05T10:00:00", ...over };
}

export const NOT_PAUSED: Paused = { on: false, at: null, by: null };
export const PAUSED: Paused = { on: true, at: "2026-11-05T10:01:00", by: "owner@example.com (owner)" };

export function pending(items: RawWaiting[] = [waiting()], paused: Paused = NOT_PAUSED) {
  return { items, paused };
}

export function visualView(): VisualView {
  return {
    items: [
      { key: "citizen@citizen_apply", role: "citizen", path: "/apply", status: "changed", diff_ratio: 0.125, run_id: "run-20261105-100000",
        case_id: "TC-0190", updated_at: "2026-11-05T10:00:00", images: { baseline: true, current: true, diff: true } },
      { key: "officer@department", role: "officer", path: "@department/", status: "changed", diff_ratio: 0.3, run_id: "run-20261105-100000",
        case_id: "TC-0197", updated_at: "2026-11-05T10:00:00", images: { baseline: true, current: true, diff: false } },
    ],
    counts: { changed: 2, baseline: 20 }, total: 2,
  };
}

export function healsView(): HealsView {
  return {
    items: [
      { id: 3, case_id: "TC-0190,TC-0191", run_id: "run-20261105-100000", kind: "locator", status: "proposed", decidable: true,
        old: { field: "mobile", label: "Mobile", path: "/apply" }, new: { field: "mobile_no", label: "Mobile number" },
        reason: "On /apply, field 'mobile' is gone; 'mobile_no' matches 92%.", created_at: "2026-11-05T10:00:00" },
      { id: 2, case_id: "TC-0201", run_id: "run-20261105-100000", kind: "workflow", status: "proposed", decidable: true,
        old: { workflow: "WF-01", step: 2, key: "click", value: "text=Verify {app_id}" }, new: { value: "text=Mark verified {app_id}", offered: "Mark verified" },
        reason: "Workflow WF-01, step 2: the control 'Verify' is gone.", created_at: "2026-11-05T10:00:00" },
      { id: 1, case_id: "TC-0050", run_id: "run-20261105-100000", kind: "manual", status: "proposed", decidable: false,
        old: { message: "<img src=x onerror=alert(1)>" }, new: {}, reason: "Not a missing-locator problem; review this test manually.",
        created_at: "2026-11-05T10:00:00" },
    ],
    counts: { proposed: 3 }, total: 3,
  };
}
