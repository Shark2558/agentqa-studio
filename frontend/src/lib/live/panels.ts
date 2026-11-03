/** The Live View's panels, folded from the events (ported from the v0.8 player): test tiles, findings, the
 *  Reconciler's rules and questions, the generated code and the requirement document. All text is kept as text. */
import { num, text, texts, type LiveEvent } from "./event";

export type TileStatus = "planned" | "running" | "passed" | "defect" | "visual" | "blocked" | "not-run" | "test-issue";
export type ShownTileStatus = Exclude<TileStatus, "planned"> | "no-result";
const RESULTS = new Set<TileStatus>(["passed", "defect", "visual", "blocked", "not-run", "test-issue"]);
const MAX_RULE_ROWS = 200;
const MAX_QUESTIONS = 200;
const MAX_BLOCKS = 3000;
const MAX_FINDINGS = 500;
const MAX_TABLE = 20;

export interface Tile { readonly id: string; readonly group: string; readonly title: string; readonly status: TileStatus; readonly message: string | null }
export type FindingKind = "defect" | "finding" | "heal" | "report";
export interface Finding {
  readonly kind: FindingKind;
  readonly severity: string | null;
  readonly title: string;
  readonly detail: string;
  readonly roles: readonly string[];
  readonly reqs: readonly string[];
  readonly order: number;
}
export interface RuleRow { readonly req: string; readonly ruleKind: string; readonly field: string; readonly status: string; readonly where: string; readonly note: string }
export interface RulesPanel { readonly counts: Readonly<Record<string, number>>; readonly rows: readonly RuleRow[]; readonly questions: readonly string[] }
export interface DocBlock { readonly kind: "file" | "heading" | "text" | "table" | "requirement"; readonly text: string; readonly level?: number; readonly rows?: readonly (readonly string[])[]; readonly req?: string }
export interface DocRequirement { readonly req: string; readonly text: string; readonly flags: readonly string[]; readonly rules: readonly string[]; readonly vague: readonly string[]; readonly rewrites: readonly string[]; readonly unclear: boolean }
export interface CodeFile { readonly file: string; readonly tests: number; readonly preview: string }

export interface PanelsModel {
  readonly tiles: ReadonlyMap<string, Tile>;
  readonly tileOrder: readonly string[];
  readonly findings: readonly Finding[];
  readonly rules: RulesPanel;
  readonly doc: { readonly blocks: readonly DocBlock[]; readonly requirements: ReadonlyMap<string, DocRequirement> };
  readonly code: ReadonlyMap<string, CodeFile>;
}

export const emptyPanels: PanelsModel = {
  tiles: new Map(), tileOrder: [], findings: [], rules: { counts: {}, rows: [], questions: [] },
  doc: { blocks: [], requirements: new Map() }, code: new Map(),
};

interface Draft {
  tiles: Map<string, Tile>;
  tileOrder: string[];
  findings: Finding[];
  counts: Record<string, number>;
  rows: RuleRow[];
  questions: string[];
  blocks: DocBlock[];
  requirements: Map<string, DocRequirement>;
  code: Map<string, CodeFile>;
}

const stripSeverity = (title: string) => title.replace(/^(Critical|High|Medium|Low):\s*/, "");
const stripReq = (value: string, req: string) => (value.startsWith(`${req}: `) ? value.slice(req.length + 2) : value);

function setTile(d: Draft, id: string, change: Partial<Tile>, group = "tests", title = ""): void {
  const known = d.tiles.get(id);
  if (!known) d.tileOrder.push(id);
  d.tiles.set(id, { ...(known ?? { id, group, title, status: "planned" as TileStatus, message: null }), ...change });
}

function onTest(d: Draft, e: LiveEvent): void {
  const id = text(e, "case");
  if (!id) return;
  if (e.agent === "designer" && e.kind === "case") {
    if (!d.tiles.has(id)) setTile(d, id, {}, text(e, "ctype") ?? "tests", e.title);
  } else if (e.kind === "test_start") {
    const file = /(\w+)\.py::/.exec(text(e, "nodeid") ?? "");
    setTile(d, id, { status: "running", message: null }, file ? `file:${file[1]}` : "run", e.title);
  } else if (e.kind === "test_end") {
    const category = text(e, "category") as TileStatus | undefined;
    setTile(d, id, { status: category && RESULTS.has(category) ? category : "test-issue", message: text(e, "message") ?? null });
  }
}

function addFinding(d: Draft, e: LiveEvent, kind: FindingKind): void {
  if (d.findings.length >= MAX_FINDINGS) return;
  d.findings.push({ kind, severity: text(e, "severity") ?? null, title: stripSeverity(e.title),
                    detail: text(e, "actual") ?? text(e, "detail") ?? "", roles: texts(e, "roles"), reqs: texts(e, "reqs"),
                    order: d.findings.length });
}

function onReconciler(d: Draft, e: LiveEvent): void {
  if (e.kind === "status") {
    const status = text(e, "status") ?? "Unknown";
    d.counts[status] = (Object.hasOwn(d.counts, status) ? d.counts[status] : 0) + 1;
    d.rows.unshift({ req: text(e, "req") ?? "app", ruleKind: (text(e, "rule_kind") ?? "").replace(/_/g, " "),
                     field: text(e, "field") ?? "", status, where: text(e, "where") ?? "", note: text(e, "note") ?? "" });
    d.rows.length = Math.min(d.rows.length, MAX_RULE_ROWS);
  } else if (e.kind === "question" && d.questions.length < MAX_QUESTIONS) {
    d.questions.push(e.title);
  }
}

function valueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "object" && !Array.isArray(value)) {
    return Object.entries(value).map(([k, v]) => `${k.replace(/_/g, " ")} ${Array.isArray(v) ? v.join("/") : String(v)}`).join(", ");
  }
  return Array.isArray(value) ? value.map(String).join("/") : String(value);
}

function ruleText(e: LiveEvent): string {
  const field = text(e, "field");
  const value = valueText(e.value);
  return `${(text(e, "rule_kind") ?? "rule").replace(/_/g, " ")}${field ? ` · ${field}` : ""}${value ? ` ${value}` : ""}`;
}

function changeRequirement(d: Draft, req: string | undefined, change: (r: DocRequirement) => Partial<DocRequirement>): void {
  if (!req) return;
  const known = d.requirements.get(req) ?? { req, text: "", flags: [], rules: [], vague: [], rewrites: [], unclear: false };
  d.requirements.set(req, { ...known, ...change(known) });
}

function tableRows(value: unknown): string[][] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, MAX_TABLE).map((row) => (Array.isArray(row) ? row.slice(0, MAX_TABLE).map((c) => String(c ?? "")) : []));
}

function onDocument(d: Draft, e: LiveEvent): void {
  const req = text(e, "req");
  const block = (b: DocBlock) => { if (d.blocks.length < MAX_BLOCKS) d.blocks.push(b); };
  if (e.agent === "writer") {
    if (e.kind === "requirement") changeRequirement(d, req, (r) => ({ rewrites: [...r.rewrites, stripReq(e.title, req ?? "")] }));
    return;
  }
  if (e.kind === "open") block({ kind: "file", text: `${text(e, "file") ?? "document"} · ${num(e, "blocks") ?? 0} block(s)` });
  else if (e.kind === "heading") block({ kind: "heading", text: e.title, level: num(e, "level") ?? 0 });
  else if (e.kind === "text") block({ kind: "text", text: e.title });
  else if (e.kind === "table") block({ kind: "table", text: e.title, rows: tableRows(e.rows) });
  else if (e.kind === "requirement" && req) {
    block({ kind: "requirement", text: e.title, req });
    changeRequirement(d, req, () => ({ text: stripReq(text(e, "text") ?? e.title, req), flags: texts(e, "flags") }));
  } else if (e.kind === "rule") changeRequirement(d, req, (r) => ({ rules: [...r.rules, ruleText(e)] }));
  else if (e.kind === "ambiguity") changeRequirement(d, req, (r) => ({ vague: [...r.vague, text(e, "term") ?? ""] }));
  else if (e.kind === "unclear") changeRequirement(d, req, () => ({ unclear: true }));
}

function apply(d: Draft, e: LiveEvent): void {
  if (e.agent === "designer" || e.agent === "executor") onTest(d, e);
  if (e.agent === "triage" && e.kind === "defect") addFinding(d, e, "defect");
  else if (e.agent === "exploratory" && e.kind === "finding") addFinding(d, e, "finding");
  else if (e.agent === "healer" && e.kind === "heal") addFinding(d, e, "heal");
  else if (e.agent === "reporter" && e.kind === "write") addFinding(d, e, "report");
  if (e.agent === "reconciler") onReconciler(d, e);
  if (e.agent === "srs" || e.agent === "writer") onDocument(d, e);
  if (e.agent === "generator" && e.kind === "write") {
    const file = text(e, "file");
    if (file) d.code.set(file, { file, tests: num(e, "tests") ?? 0, preview: text(e, "preview") ?? "" });
  }
}

/** The panels after `events`; the panels given are never changed. */
export function foldPanels(p: PanelsModel, events: readonly LiveEvent[]): PanelsModel {
  if (events.length === 0) return p;
  const d: Draft = {
    tiles: new Map(p.tiles), tileOrder: [...p.tileOrder], findings: [...p.findings], counts: { ...p.rules.counts },
    rows: [...p.rules.rows], questions: [...p.rules.questions], blocks: [...p.doc.blocks],
    requirements: new Map(p.doc.requirements), code: new Map(p.code),
  };
  for (const e of events) apply(d, e);
  return { tiles: d.tiles, tileOrder: d.tileOrder, findings: d.findings, rules: { counts: d.counts, rows: d.rows, questions: d.questions },
           doc: { blocks: d.blocks, requirements: d.requirements }, code: d.code };
}

/** What a tile shows: a planned case is "not run"; a test still running when the run is over has "no result". */
export function tileStatus(tile: Tile, runOver: boolean): ShownTileStatus {
  if (tile.status === "planned") return "not-run";
  if (tile.status === "running") return runOver ? "no-result" : "running";
  return tile.status;
}

export function tileCounts(p: PanelsModel, runOver: boolean): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const tile of p.tiles.values()) {
    const s = tileStatus(tile, runOver);
    counts[s] = (counts[s] ?? 0) + 1;
  }
  return counts;
}

const RANK: Readonly<Record<string, number>> = { Critical: 0, High: 1, Medium: 2, Low: 3 };
const rank = (f: Finding) => (f.severity && Object.hasOwn(RANK, f.severity) ? RANK[f.severity] : 4);

/** Findings worst first; once triage has drafted defects, the exploratory findings are folded into them. */
export function shownFindings(p: PanelsModel): Finding[] {
  const hasDefects = p.findings.some((f) => f.kind === "defect");
  return p.findings.filter((f) => !(hasDefects && f.kind === "finding")).sort((a, b) => rank(a) - rank(b) || a.order - b.order);
}
