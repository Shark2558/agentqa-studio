/** M1.4 Phase C's API: the help box (what waits, answers, take-over commands, pause and resume), visual review and
 *  heals. Text in these answers comes from the application under test: render it as text only. */
import { request } from "./api";
import { cleanPending, type Answer, type Command, type Paused, type Pending } from "./assist";
import { PAGE, post, project, query } from "./gatesApi";

const BASE = "/api/v1";

export type VisualShow = "changed" | "all" | "approved" | "reported" | "baseline" | "same";
export type Picture = "baseline" | "current" | "diff";
export interface VisualItem {
  key: string;
  role: string | null;
  path: string | null;
  status: string;
  diff_ratio: number | null;
  run_id: string | null;
  case_id: string | null;
  updated_at: string | null;
  images: Record<Picture, boolean>;
}
export interface VisualView { items: VisualItem[]; counts: Record<string, number>; total: number }
export type VisualDecision = "approve" | "defect";
export interface VisualDecided { key: string; status: string; defect?: string }

export type HealValues = Record<string, string | number | boolean | null>;
export interface Heal {
  id: number;
  case_id: string | null;
  run_id: string | null;
  kind: string;
  old: HealValues;
  new: HealValues;
  reason: string;
  status: string;
  created_at: string | null;
  decidable: boolean;
}
export interface HealsView { items: Heal[]; counts: Record<string, number>; total: number }
export type HealDecision = "approve" | "reject";

export const reviewApi = {
  assist: async (slug: string): Promise<Pending> => cleanPending(await request<unknown>(`${project(slug)}/assist`)),
  answer: (slug: string, id: number, body: Answer) => request<{ id: number; status: string }>(`${project(slug)}/assist/${id}/answer`, post(body)),
  command: (slug: string, id: number, body: Command) => request<{ id: number }>(`${project(slug)}/assist/${id}/commands`, post(body)),
  pause: (slug: string) => request<Paused>(`${project(slug)}/pause`, post({})),
  resume: (slug: string) => request<Paused & { handed_back: number }>(`${project(slug)}/resume`, post({})),

  visual: (slug: string, show: VisualShow) => request<VisualView>(`${project(slug)}/visual${query({ show, limit: PAGE })}`),
  decideVisual: (slug: string, key: string, decision: VisualDecision, why: string) =>
    request<VisualDecided>(`${project(slug)}/visual/${encodeURIComponent(key)}`, post({ decision, why })),
  approveAllVisual: (slug: string, why: string) => request<{ approved: number; skipped: number }>(`${project(slug)}/visual/approve-all`, post({ why })),

  heals: (slug: string, status?: string) => request<HealsView>(`${project(slug)}/heals${query({ status, limit: PAGE })}`),
  decideHeal: (slug: string, id: number, decision: HealDecision, why: string) =>
    request<{ id: number; status: string; note: string }>(`${project(slug)}/heals/${id}`, post({ decision, why })),
};

/** Picture addresses: by question id and version, or by screen key and which picture, never by a file path. */
export const reviewFiles = {
  shot: (slug: string, id: number, version: number) => `${BASE}${project(slug)}/assist/${id}/shot?v=${version}`,
  visual: (slug: string, key: string, which: Picture) => `${BASE}${project(slug)}/visual/${encodeURIComponent(key)}/${which}`,
};
