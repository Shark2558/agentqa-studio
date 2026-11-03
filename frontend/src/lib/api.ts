/** The API client: one envelope, the CSRF header on every state-changing call, cookies for the session. */

export type Envelope<T> =
  | { ok: true; data: T }
  | { ok: false; error: { code: string; message: string } };

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const BASE = "/api/v1";
const CSRF_HEADER = "X-Requested-With";
const CSRF_VALUE = "AgentQA";

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== "GET" && method !== "HEAD") headers.set(CSRF_HEADER, CSRF_VALUE);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(BASE + path, { ...init, method, headers, credentials: "same-origin" });
  const body = (await response.json().catch(() => null)) as Envelope<T> | null;
  if (!body) throw new ApiError(response.status, "bad_response", "The server did not answer with JSON");
  if (!body.ok) throw new ApiError(response.status, body.error.code, body.error.message);
  return body.data;
}

export const api = {
  health: () => request<{ status: string; version: string; owner_configured: boolean }>("/health"),
  me: () => request<User>("/auth/me"),
  login: (email: string, password: string) =>
    request<User>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<{ signed_out: boolean }>("/auth/logout", { method: "POST" }),
  projects: () => request<ProjectSummary[]>("/projects"),
  project: (slug: string) => request<ProjectSummary>(`/projects/${encodeURIComponent(slug)}`),
  createProject: (name: string, url: string, environment = "Test / QA") =>
    request<ProjectSummary>("/projects", { method: "POST", body: JSON.stringify({ name, url, environment }) }),
  createDemo: () => request<ProjectSummary>("/projects/demo", { method: "POST" }),
  preflight: (url: string) => request<Preflight>("/preflight", { method: "POST", body: JSON.stringify({ url }) }),
  documents: (slug: string) => request<DocumentInfo[]>(`/projects/${encodeURIComponent(slug)}/documents`),
  deleteDocument: (slug: string, name: string) =>
    request<{ deleted: string }>(`/projects/${encodeURIComponent(slug)}/documents/${encodeURIComponent(name)}`, { method: "DELETE" }),
  uploadUrl: (slug: string, folder: "documents" | "imports") => `${BASE}/projects/${encodeURIComponent(slug)}/${folder}`,
  typedRequirements: (slug: string, text: string, answers: { question: string; answer: string; topic: string }[] = [], items: string[] = []) =>
    request<ChatResult>(`/projects/${encodeURIComponent(slug)}/requirements/typed`, { method: "POST", body: JSON.stringify({ text, answers, items }) }),
  requirements: (slug: string) => request<RequirementsView>(`/projects/${encodeURIComponent(slug)}/requirements`),
  accounts: (slug: string) => request<AccountsView>(`/projects/${encodeURIComponent(slug)}/accounts`),
  saveAccounts: (slug: string, body: { no_login: boolean; roles: RoleInput[] }) =>
    request<AccountsView>(`/projects/${encodeURIComponent(slug)}/accounts`, { method: "PUT", body: JSON.stringify(body) }),
  runs: (slug: string) => request<Run[]>(`/projects/${encodeURIComponent(slug)}/runs`),
  startRun: (slug: string, body: RunRequest) =>
    request<Run>(`/projects/${encodeURIComponent(slug)}/runs`, { method: "POST", body: JSON.stringify(body) }),
  liveSessions: (slug: string) => request<LiveSession[]>(`/projects/${encodeURIComponent(slug)}/live/sessions`),
  streamUrl: (slug: string, session: string) =>
    `${BASE}/projects/${encodeURIComponent(slug)}/live/${encodeURIComponent(session)}/stream`,
};

export interface User {
  email: string;
  role: string;
}

/** Upload one or more files with progress (fetch has no upload progress, so this is the one XHR in the app). */
export function upload(url: string, files: File[], onProgress: (fraction: number) => void): Promise<DocumentInfo[]> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.setRequestHeader(CSRF_HEADER, CSRF_VALUE);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onerror = () => reject(new ApiError(0, "network", "The upload did not reach the server"));
    xhr.onabort = () => reject(new ApiError(0, "network", "The upload was cancelled"));
    xhr.ontimeout = () => reject(new ApiError(0, "network", "The upload timed out"));
    xhr.onload = () => {
      let body: Envelope<DocumentInfo[]> | null = null;
      try {
        body = JSON.parse(xhr.responseText) as Envelope<DocumentInfo[]>;
      } catch {
        body = null;
      }
      if (!body) return reject(new ApiError(xhr.status, "bad_response", "The server did not answer with JSON"));
      if (!body.ok) return reject(new ApiError(xhr.status, body.error.code, body.error.message));
      resolve(body.data);
    };
    xhr.send(form);
  });
}

export interface Preflight {
  reachable: boolean;
  status: number | null;
  final_url: string | null;
  login_detected: boolean;
  login_url: string | null;
  fix: string | null;
}

export interface DocumentInfo {
  name: string;
  folder: string;
  size: number;
  kind: string;
  status: "read" | "partly" | "unread";
  detail: string;
  segments: number;
  read_at?: string | null;
}

export interface ChatItem {
  id: string;
  text: string;
  kind: "requirement" | "story" | "gherkin";
  flags: { word: string; why: string }[];
}

export interface ChatQuestion {
  id: string;
  topic: string;
  question: string;
}

export interface ChatResult {
  items: ChatItem[];
  questions: ChatQuestion[];
  source: "rules" | "ai";
}

export interface Requirement {
  id: string;
  seq: number;
  section: string | null;
  text: string;
  kind: string | null;
  priority: string | null;
  roles: string[] | null;
  ambiguity: unknown[] | null;
  source_file: string | null;
  disposition: string | null;
}

export interface RequirementsView {
  requirements: Requirement[];
  documents: { name: string; kind: string; status: string; detail: string; segments: number; read_at?: string }[];
}

export interface RoleInput {
  uid?: string;          // the wizard's own row key; never sent
  role: string;
  login_option: string;
  method: string;
  username?: string;
  mobile?: string;
  email?: string;
  password?: string;
  otp_source?: string;
  otp_fixed?: string;
  aliases?: string[];
}

export interface AccountRow extends RoleInput {
  has_password: boolean;
  has_fixed_otp: boolean;
  has_totp: boolean;
}

export interface AccountsView {
  no_login: boolean;
  roles: AccountRow[];
}

export interface ProjectSummary {
  slug: string;
  name: string;
  url: string;
  environment?: string;
  cases?: number;
  defects?: number;
  last?: string | null;
  score?: number;
  verdict?: string;
}

export interface Run {
  id: number;
  stage: string;
  status: "running" | "done" | "failed" | string;
  started_at: string;
  finished_at: string | null;
  exit_code: number | null;
}

export interface RunRequest {
  scope: string;
  policy?: string;
  auto_approve?: boolean;
  headed?: boolean;
}

export interface LiveSession {
  id: string;
  label: string;
  running: boolean;
  when: string;
  shots: number;
}

export interface LiveEvent {
  t: number;
  seq: number;
  w: string;
  agent: string;
  kind: string;
  title: string;
  level?: string;
  stage?: string;
  [key: string]: unknown;
}
