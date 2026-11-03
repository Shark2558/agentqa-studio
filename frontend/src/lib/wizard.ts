/** The new-project wizard's state: six steps, what each needs before "Continue", derived purely from actions. */
import type { ChatResult, DocumentInfo, RoleInput } from "./api";

export const STEPS = [
  { key: "basics", title: "Name and address", why: "AgentQA needs to know what to test and whether it may change data there." },
  { key: "requirements", title: "Requirements", why: "Tests come from what the application must do; a document or your own words both work." },
  { key: "accounts", title: "Accounts", why: "Most portals show different screens to different kinds of users; one test account per kind lets AgentQA see them all." },
  { key: "ai", title: "AI mode", why: "AI is optional. Without it AgentQA still reads documents, explores and tests by rules." },
  { key: "schedule", title: "Schedule", why: "A repeating run catches regressions while nobody is watching." },
  { key: "review", title: "Review and start", why: "A last look before the agents begin." },
] as const;

export type StepKey = (typeof STEPS)[number]["key"];
export type Environment = "Development" | "Test / QA" | "UAT" | "Staging" | "Production";

export interface WizardState {
  step: number;
  name: string;
  url: string;
  environment: Environment;
  slug: string | null;
  documents: DocumentInfo[];
  typed: string;
  chat: ChatResult | null;
  answers: Record<string, string>;
  confirmed: boolean;
  noLogin: boolean;
  roles: RoleInput[];
}

export type WizardAction =
  | { type: "field"; field: "name" | "url" | "typed"; value: string }
  | { type: "field"; field: "environment"; value: Environment }
  | { type: "field"; field: "noLogin"; value: boolean }
  | { type: "created"; slug: string }
  | { type: "document"; doc: DocumentInfo }
  | { type: "removeDocument"; name: string }
  | { type: "chat"; chat: ChatResult }
  | { type: "answer"; id: string; answer: string }
  | { type: "confirm" }
  | { type: "addRole" }
  | { type: "role"; index: number; role: RoleInput }
  | { type: "removeRole"; index: number }
  | { type: "next" }
  | { type: "back" }
  | { type: "goto"; step: number };

let rowCounter = 0;
export function newRole(): RoleInput {
  rowCounter += 1;
  return { uid: `role-${rowCounter}`, role: "", login_option: "Login", method: "password" };
}

export const initialWizard: WizardState = {
  step: 0, name: "", url: "", environment: "Test / QA", slug: null, documents: [], typed: "", chat: null,
  answers: {}, confirmed: false, noLogin: false, roles: [newRole()],
};

/** What the API receives: the rows the owner filled, without the wizard's own row keys. */
export function rolesForApi(s: WizardState): RoleInput[] {
  return s.noLogin ? [] : s.roles.filter((r) => r.role.trim()).map((r) => ({ ...r, uid: undefined }));
}

/** The answers the owner gave, paired with the chat's questions and topics. */
export function answersForApi(s: WizardState): { question: string; answer: string; topic: string }[] {
  return (s.chat?.questions ?? []).map((q) => ({ question: q.question, answer: s.answers[q.id] ?? "", topic: q.topic }));
}

const WEB_ADDRESS = /^https?:\/\/[^\s/]+/;

export function canContinue(s: WizardState): boolean {
  switch (STEPS[s.step].key) {
    case "basics":
      return s.name.trim().length > 0 && WEB_ADDRESS.test(s.url.trim());
    case "requirements":
      return s.documents.some((d) => d.status !== "unread") || s.typed.trim().length > 0;
    case "accounts":
      return s.noLogin || s.roles.some((r) => r.role.trim().length > 0 && r.login_option.trim().length > 0);
    default:
      return true;
  }
}

function clamp(step: number): number {
  return Math.min(STEPS.length - 1, Math.max(0, step));
}

export function reduceWizard(s: WizardState, a: WizardAction): WizardState {
  switch (a.type) {
    case "field":
      return a.field === "typed" ? { ...s, typed: a.value as string, confirmed: false } : { ...s, [a.field]: a.value };
    case "created":
      return { ...s, slug: a.slug };
    case "document":
      return { ...s, documents: [...s.documents.filter((d) => d.name !== a.doc.name), a.doc] };
    case "removeDocument":
      return { ...s, documents: s.documents.filter((d) => d.name !== a.name) };
    case "chat":
      return { ...s, chat: a.chat, answers: {}, confirmed: false };
    case "answer":
      return { ...s, answers: { ...s.answers, [a.id]: a.answer } };
    case "confirm":
      return { ...s, confirmed: true };
    case "addRole":
      return { ...s, roles: [...s.roles, newRole()] };
    case "role":
      return { ...s, roles: s.roles.map((r, i) => (i === a.index ? a.role : r)) };
    case "removeRole":
      return { ...s, roles: s.roles.filter((_, i) => i !== a.index) };
    case "next":
      return { ...s, step: clamp(s.step + 1) };
    case "back":
      return { ...s, step: clamp(s.step - 1) };
    case "goto":
      return { ...s, step: clamp(a.step) };
  }
}
