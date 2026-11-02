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
  createProject: (name: string, url: string) =>
    request<ProjectSummary>("/projects", { method: "POST", body: JSON.stringify({ name, url }) }),
  createDemo: () => request<ProjectSummary>("/projects/demo", { method: "POST" }),
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

export interface ProjectSummary {
  slug: string;
  name: string;
  url: string;
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
