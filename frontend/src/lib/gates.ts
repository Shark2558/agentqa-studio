/** The gates' rules as the pages use them (pure): selections, which decisions need a reason, the downloads, who made a
 *  change, the re-plan policy, error words, the navigation badges and the "What needs you" list. */
import { ApiError } from "./api";
import { gateFiles, type Change, type Defect, type GateCounts, type Policy } from "./gatesApi";

export type Selection = ReadonlySet<string>;

/** The selected ids that are still shown, in the order shown: a list that refreshed or changed tab under a selection
 *  never decides rows the person can no longer see. */
export function inView(sel: Selection, shown: readonly string[]): string[] {
  return shown.filter((id) => sel.has(id));
}

/** A defect sent to a tracker cannot be decided again (the server answers 409 `exported`), so it is never selectable. */
export function isDecidableDefect(d: Pick<Defect, "status" | "external_key">): boolean {
  return d.status !== "exported" && !d.external_key;
}

/** An answer's change-log row carries the question it answers, not a person's reason (the engine writes "answered '…'"
 *  with the question as its justification; `test_gates_engine.py` pins that wording). */
export function whyIsQuestion(c: Pick<Change, "object" | "change" | "why">): boolean {
  return Boolean(c.why) && c.object === "question" && c.change.startsWith("answered");
}

/** A new set with `id` added or removed; the input is never changed. */
export function toggle(sel: Selection, id: string): Selection {
  const next = new Set(sel);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

/** A new set with every id in `ids` added (`on`) or removed. */
export function setMany(sel: Selection, ids: readonly string[], on: boolean): Selection {
  const next = new Set(sel);
  for (const id of ids) {
    if (on) next.add(id);
    else next.delete(id);
  }
  return next;
}

export type ReasonFor = "cases" | "type" | "imported" | "defects" | "disposition" | "reopen" | "approve";
// Rejecting, undoing (reset, review, back to draft, reopen) and overriding a computed status need a reason; approving
// and confirming do not (decision 4 and the Phase A record, items 4 and 6).
const NEEDS_WHY: Readonly<Record<ReasonFor, ReadonlySet<string> | "always">> = {
  cases: new Set(["reject", "reset"]), type: new Set(["reject"]), imported: new Set(["reject", "review"]),
  defects: new Set(["rejected", "draft"]), disposition: "always", reopen: "always", approve: new Set(),
};

export function needsWhy(what: ReasonFor, decision: string): boolean {
  const rule = NEEDS_WHY[what];
  return rule === "always" || rule.has(decision);
}

export const WHY_MAX = 500;

/** A reason as the server stores it: one line, trimmed, at most 500 characters. */
export function cleanWhy(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ").slice(0, WHY_MAX);
}

export interface ExportLink { id: "jira" | "zoho"; label: string; href: string }

export function exportLinks(slug: string, drafts: boolean): ExportLink[] {
  return [
    { id: "jira", label: "Defects for Jira (CSV)", href: gateFiles.defectsCsv(slug, "jira", drafts) },
    { id: "zoho", label: "Defects for Zoho (CSV)", href: gateFiles.defectsCsv(slug, "zoho", drafts) },
  ];
}

/** Who made a change: a person as recorded ("email (role)"), or AgentQA's own writers by name. */
export function byWords(by: string | null | undefined): string {
  if (!by) return "not recorded";
  if (by === "agents") return "AgentQA's agents";
  if (by === "dashboard") return "someone in the old dashboard";
  return by;
}

/** A stored time ("2026-11-04T03:48:26") as "2026-11-04 03:48", or a dash when there is none. */
export function when(iso: string | null | undefined): string {
  return iso ? iso.replace("T", " ").slice(0, 16) : "—";
}

const DIVERGENCE: Readonly<Record<string, string>> = {
  ask: "it asks you whenever the requirements and the application disagree",
  srs_wins: "the requirements document wins whenever the two disagree",
  app_wins: "what the application does wins whenever the two disagree",
};

/** project.yaml's rule for disagreements, which "Apply my answers and re-plan" uses (Phase A record, item 1). */
export function policyWords(policy: Policy): string {
  return Object.hasOwn(DIVERGENCE, policy.divergence) ? DIVERGENCE[policy.divergence] : `the rule “${policy.divergence}” in project.yaml`;
}

const ERROR_WORDS: Readonly<Record<string, string>> = {
  not_open: "Someone already answered this question: reopen it first to change the answer.",
  not_answered: "This question has no answer to reopen.",
  plan_changed: "The plan changed since you opened it: review it again, then approve.",
  busy: "A run is going: wait until it finishes, then try again.",
  exported: "This defect was already sent to a tracker, so it cannot be decided again here.",
  read_only: "You can look but not change anything (Viewer).",
  csrf: "Start this from AgentQA's own pages.",
  not_found: "It no longer exists: reload the page.",
  network: "The server could not be reached: check that it is still running.",
};

/** A refusal in plain words: the gate's own codes are worded here; a validation message is the server's. */
export function errorWords(error: unknown): string {
  if (error instanceof TypeError) return ERROR_WORDS.network;            // fetch itself failed: no answer at all
  if (!(error instanceof ApiError)) return "Something went wrong: try again, or reload the page.";
  if (Object.hasOwn(ERROR_WORDS, error.code)) return ERROR_WORDS[error.code];
  return error.message || "Something went wrong: try again, or reload the page.";
}

// Refusals that mean "what you see is out of date": the page reloads what it shows so the next try starts fresh.
const STALE = new Set(["busy", "not_open", "not_answered", "exported", "not_found", "plan_changed"]);
export const isStale = (error: unknown): boolean => error instanceof ApiError && STALE.has(error.code);

const POLL_MS = { running: 5_000, idle: 30_000, error: 60_000 } as const;
const GIVE_UP = new Set([401, 403, 404]);         // signed out, not allowed, no such project: asking again cannot help

/** How often to ask for the gate counts: often during a run, less when idle, slowly after a blip; never after a
 *  refusal that asking again cannot change. */
export function gatePollMs(c: GateCounts | undefined, error: unknown): number | false {
  if (error instanceof ApiError && GIVE_UP.has(error.status)) return false;
  if (error) return POLL_MS.error;
  return c?.running ? POLL_MS.running : POLL_MS.idle;
}

export interface Badge { text: string; name: string }
export interface NavBadges { questions: Badge | null; plan: Badge | null; defects: Badge | null }

const count = (n: number, name: string): Badge | null => (n > 0 ? { text: String(n), name: `${n} ${name}` } : null);

/** What each gate's link shows: open questions, cases still to review while the plan waits, drafts to confirm. */
export function navBadges(c: GateCounts | undefined): NavBadges {
  if (!c) return { questions: null, plan: null, defects: null };
  const waiting = c.plan.exists && !c.plan.approved;
  const toReview = c.plan.proposed + c.imported_ready;
  const plan = !waiting ? null : toReview > 0 ? { text: String(toReview), name: `${toReview} to review` } : { text: "•", name: "waiting for your approval" };
  return { questions: count(c.questions_open, "open"), plan, defects: count(c.defects_draft, "to confirm") };
}

export interface NeedItem { id: string; text: string; to: string | null }
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The Project page's "What needs you": every item that waits for a person, with the page that answers it. Visual
 *  review and heals get their pages in Phase C; until then they are named without a link. Someone who cannot decide
 *  (a Viewer) reads the same items as what is waiting, not as tasks for them (sitting 1, S5). */
export function needsYou(c: GateCounts, slug: string, mayDecide: boolean): NeedItem[] {
  const base = `/projects/${encodeURIComponent(slug)}`;
  const review = mayDecide ? "to review" : "waiting for review";
  const items: (NeedItem | false)[] = [
    c.assist_pending > 0 && { id: "assist", text: `An agent is waiting for ${mayDecide ? "you" : "a person"}`, to: `${base}/live` },
    c.questions_open > 0 && {
      id: "questions", to: `${base}/questions`,
      text: mayDecide ? `${plural(c.questions_open, "question", "questions")} to answer` : plural(c.questions_open, "open question", "open questions"),
    },
    c.plan.exists && !c.plan.approved && {
      id: "plan", to: `${base}/plan`,
      text: `The test plan waits for ${mayDecide ? "your " : ""}approval${c.plan.proposed ? `: ${plural(c.plan.proposed, "case", "cases")} to review` : ""}`,
    },
    c.imported_ready > 0 && {
      id: "imported", to: `${base}/plan`,
      text: `${plural(c.imported_ready, "imported manual case is", "imported manual cases are")} ${mayDecide ? "ready to approve" : "waiting for approval"}`,
    },
    c.defects_draft > 0 && {
      id: "defects", to: `${base}/defects`,
      text: `${plural(c.defects_draft, "defect", "defects")} ${mayDecide ? "to confirm or reject" : "waiting for a decision"}`,
    },
    c.visual_changed > 0 && { id: "visual", text: `${plural(c.visual_changed, "changed screen", "changed screens")} ${review} (in the old dashboard for now)`, to: null },
    c.heals_proposed > 0 && { id: "heals", text: `${plural(c.heals_proposed, "proposed fix", "proposed fixes")} ${review} (in the old dashboard for now)`, to: null },
  ];
  return items.filter((i): i is NeedItem => i !== false);
}

export type GateId = "questions" | "plan" | "defects";
export interface BoardGates { questions: number; defects: number; plan: string }

/** A gate's words on the Live View's pipeline card: what the recording counted, plus what is still open now when the
 *  run shown is the newest (`now` is null for older runs, whose gates have since moved on). */
export function liveGateText(id: GateId, board: BoardGates, now: GateCounts | null): string {
  if (id === "questions") {
    if (now) return `${board.questions} asked · ${now.questions_open} open`;
    return board.questions ? `${board.questions} for you` : "none";
  }
  if (id === "defects") {
    if (now) return `${board.defects} found · ${now.defects_draft} to confirm`;
    return board.defects ? `${board.defects} to confirm` : "none";
  }
  // An approval made in the app leaves no line in the recording (plan fact 12), so the newest run asks the store.
  const approved = now ? now.plan.approved : board.plan === "approved";
  if (approved) return "approved";
  return board.plan === "waiting" || (now && now.plan.exists) ? "waiting for you" : "not yet";
}
