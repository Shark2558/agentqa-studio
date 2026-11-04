/** The three gates' API (M1.4): questions, the test plan, defects, requirement dispositions, the change log and the gate
 *  counts. Text in these answers comes from the application under test and its documents: render it as text only. */
import { request, type Requirement, type Run } from "./api";

const BASE = "/api/v1";
const project = (slug: string) => `/projects/${encodeURIComponent(slug)}`;
const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
/** `?a=1&b=x` from the defined values only. */
function query(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export interface GateCounts {
  questions_open: number;
  plan: { exists: boolean; approved: boolean; proposed: number; cases: number; digest: string | null };
  imported_ready: number;
  defects_draft: number;
  defects_open: number;
  visual_changed: number;
  heals_proposed: number;
  assist_pending: number;
  paused: boolean;
  running: boolean;
}

export interface QuestionOption { label: string; needs_value: boolean }
export interface Question {
  id: number;
  kind: string;
  question: string;
  options: QuestionOption[];
  proposed: string | null;
  priority: string | null;
  req_id: string | null;
  rule_id: string | null;
  status: "open" | "answered" | string;
  answer: string | null;
  choice: number | null;
  value: string;
  answered_at: string | null;
}
/** The rules a re-plan will reconcile with: the last run's (`source` "run"), else project.yaml's ("project"). */
export interface Policy { divergence: string; inferred_access: string; source: "run" | "project" }
export interface QuestionsView {
  items: Question[];
  counts: { open: number; answered: number };
  total: number;
  policy: Policy;
}

export type CaseStatus = "proposed" | "approved" | "rejected";
export interface PlanState {
  approved: boolean;
  approved_at: string | null;
  digest: string | null;
  summary: PlanSummary | null;
}
export interface PlanSummary {
  cases: number;
  by_status?: Record<string, number>;
  requirements?: number;
  requirements_covered?: number;
  open_questions?: number;
  risk_notes?: string[];
  [key: string]: unknown;
}
export interface TypeRow { type: string; cases: number; approved: number; rejected: number; proposed: number }
/** As `orchestrator/gates/plan.py _gaps` sends them: requirement ids, documents not fully read, cases a production
 *  application never runs. */
export interface PlanGaps {
  untested: string[];
  clarify: string[];
  unread: { name: string; status: string; detail: string | null }[];
  missed: number;
  workflow: { req_id: string; why: string }[];
  production: { key: string; title: string; path: string | null }[];
}
export interface ImportedCounts { ready: number; review: number; approved: number; rejected: number }
export interface PlanView { plan: PlanState; types: TypeRow[]; gaps: PlanGaps; imported: ImportedCounts; running: boolean }
export interface TestCase {
  id: string;
  type: string;
  title: string;
  role: string | null;
  path: string | null;
  priority: string | null;
  oracle_source: string | null;
  req_ids: string[] | null;
  status: CaseStatus | string;
}
export interface Page<T> { items: T[]; total: number }
export type CaseDecision = "approve" | "reject" | "reset";
export type ImportedDecision = "approve_ready" | "approve" | "reject" | "review";

export interface Evidence { n: number; kind: string | null; role: string | null; image: boolean }
export interface Defect {
  id: string;
  severity: string;
  priority: string | null;
  title: string;
  role: string | null;
  url: string | null;
  steps: string | null;
  expected: string | null;
  actual: string | null;
  req_ids: string[] | null;
  case_ids: string[] | null;
  status: string;
  created_at: string | null;
  notes: string | null;
  external_key: string | null;
  evidence: Evidence[];
}
export interface DefectsView extends Page<Defect> {
  counts: { open_by_severity: Record<string, number>; by_status: Record<string, number> };
}
export type DefectDecision = "confirmed" | "rejected" | "draft";

export interface GatedRequirement extends Requirement { disposition_note: string | null }
export interface RequirementsPage {
  requirements: GatedRequirement[];
  documents: { name: string; kind: string; status: string; detail: string; segments: number; read_at?: string }[];
  total: number;
}
export type Disposition = "out_of_scope" | "not_testable" | "manual" | "clarify";

export interface Change {
  id: number;
  at: string;
  agent: string;
  object: string;
  object_id: string;
  change: string;
  why: string | null;
  by: string | null;
}
export interface ChangesPage { items: Change[]; next_before: number | null }

/** A page of rows: the API's own cap. */
export const PAGE = 200;

export const gatesApi = {
  counts: (slug: string) => request<GateCounts>(`${project(slug)}/gates`),

  questions: (slug: string, status?: "open" | "answered") =>
    request<QuestionsView>(`${project(slug)}/questions${query({ status, limit: PAGE })}`),
  answer: (slug: string, qid: number, choice: number, value: string) =>
    request<Question>(`${project(slug)}/questions/${qid}/answer`, post({ choice, value })),
  reopen: (slug: string, qid: number, why: string) => request<Question>(`${project(slug)}/questions/${qid}/reopen`, post({ why })),
  applyAnswers: (slug: string) => request<Run>(`${project(slug)}/questions/apply`, post({})),

  plan: (slug: string) => request<PlanView>(`${project(slug)}/plan`),
  cases: (slug: string, filter: { type?: string; status?: CaseStatus; offset?: number }) =>
    request<Page<TestCase>>(`${project(slug)}/plan/cases${query({ type: filter.type, status: filter.status, limit: PAGE, offset: filter.offset })}`),
  decideCases: (slug: string, ids: readonly string[], decision: CaseDecision, why: string) =>
    request<{ changed: number; plan: PlanState }>(`${project(slug)}/plan/cases`, post({ ids, decision, why })),
  decideType: (slug: string, ctype: string, decision: "approve" | "reject", why: string) =>
    request<{ changed: number; plan: PlanState }>(`${project(slug)}/plan/types/${encodeURIComponent(ctype)}`, post({ decision, why })),
  decideImported: (slug: string, ids: readonly string[], decision: ImportedDecision, why: string) =>
    request<{ changed: number; plan: PlanState }>(`${project(slug)}/plan/imported`, post({ ids, decision, why })),
  approvePlan: (slug: string, digest: string, why: string) => request<PlanState>(`${project(slug)}/plan/approve`, post({ digest, why })),

  defects: (slug: string, status?: string) => request<DefectsView>(`${project(slug)}/defects${query({ status, limit: PAGE })}`),
  decideDefects: (slug: string, ids: readonly string[], decision: DefectDecision, why: string) =>
    request<{ changed: number }>(`${project(slug)}/defects/decisions`, post({ ids, decision, why })),

  requirements: (slug: string, offset = 0) =>
    request<RequirementsPage>(`${project(slug)}/requirements${query({ limit: PAGE, offset: offset || undefined })}`),
  setDisposition: (slug: string, rid: string, disposition: Disposition, why: string) =>
    request<GatedRequirement>(`${project(slug)}/requirements/${encodeURIComponent(rid)}`, { method: "PATCH", body: JSON.stringify({ disposition, why }) }),

  changes: (slug: string, before?: number | null) => request<ChangesPage>(`${project(slug)}/changes${query({ limit: 50, before })}`),
};

/** Download and image addresses: plain links from the app's own pages (the server refuses a download started from
 *  another site). Pages never hold a file path, only these addresses. */
export const gateFiles = {
  testCases: (slug: string) => `${BASE}${project(slug)}/plan/testcases.xlsx`,
  rtm: (slug: string) => `${BASE}${project(slug)}/requirements/rtm.xlsx`,
  defectsCsv: (slug: string, kind: "jira" | "zoho", drafts: boolean) =>
    `${BASE}${project(slug)}/defects/${kind === "jira" ? "export.csv" : "zoho.csv"}?drafts=${drafts ? 1 : 0}`,
  evidence: (slug: string, did: string, n: number) => `${BASE}${project(slug)}/defects/${encodeURIComponent(did)}/evidence/${n}`,
};
