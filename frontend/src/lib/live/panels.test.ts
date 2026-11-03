import { describe, expect, it } from "vitest";
import { demoBoard } from "../../test-fixtures/live";
import { emptyBoard, foldBoard } from "./board";
import { toEvent, type LiveEvent } from "./event";
import { emptyLanes, foldLanes } from "./lanes";
import { emptyPanels, foldPanels, shownFindings, tileCounts, tileStatus } from "./panels";

let seq = 0;
function ev(t: number, agent: string, kind: string, extra: Record<string, unknown> = {}): LiveEvent {
  seq += 1;
  return toEvent({ t, seq, w: "main", agent, kind, title: `${agent} ${kind}`, phase: "result", ...extra }) as LiveEvent;
}
const panels = (events: LiveEvent[]) => foldPanels(emptyPanels, events);

describe("tiles: one square per test, never a pass that was not a pass", () => {
  it("a designed case is planned, a started one runs, an ended one shows its result", () => {
    const p = panels([
      ev(1, "designer", "case", { case: "TC-0001", ctype: "page_smoke", title: "TC-0001 Home loads" }),
      ev(2, "designer", "case", { case: "TC-0002", ctype: "page_smoke" }),
      ev(3, "executor", "test_start", { case: "TC-0001", nodeid: "tests/test_pages.py::test_home" }),
      ev(4, "executor", "test_end", { case: "TC-0001", category: "passed" }),
      ev(5, "executor", "test_start", { case: "TC-0002" }),
    ]);
    expect(p.tiles.get("TC-0001")?.status).toBe("passed");
    expect(p.tiles.get("TC-0002")?.status).toBe("running");
    expect(p.tileOrder).toEqual(["TC-0001", "TC-0002"]);
  });

  it.each(["defect", "visual", "blocked", "not-run", "test-issue"])("keeps %s apart from passed", (category) => {
    const p = panels([ev(1, "executor", "test_end", { case: "TC-9", category })]);
    expect(p.tiles.get("TC-9")?.status).toBe(category);
  });

  it("an unknown category is a test issue, never a pass", () => {
    expect(panels([ev(1, "executor", "test_end", { case: "TC-9", category: "great" })]).tiles.get("TC-9")?.status).toBe("test-issue");
  });

  it("a test that started but has no end shows 'no result' once the run is over, and a never-run case 'not run'", () => {
    const p = panels([ev(1, "designer", "case", { case: "TC-1" }), ev(2, "executor", "test_start", { case: "TC-2" })]);
    const board = foldBoard(emptyBoard(demoBoard), [], demoBoard);
    expect(tileStatus(p.tiles.get("TC-2")!, true)).toBe("no-result");
    expect(tileStatus(p.tiles.get("TC-2")!, false)).toBe("running");
    expect(tileStatus(p.tiles.get("TC-1")!, true)).toBe("not-run");
    expect(tileCounts(p, true)).toEqual({ "no-result": 1, "not-run": 1 });
    expect(board.order.length).toBe(12);
  });
});

describe("findings: worst first, exploratory findings folded into the defects", () => {
  it("sorts defects by severity", () => {
    const p = panels([
      ev(1, "triage", "defect", { severity: "Low", title: "Low: alt text" }),
      ev(2, "triage", "defect", { severity: "Critical", title: "Critical: open queue" }),
      ev(3, "triage", "defect", { severity: "High", title: "High: crash" }),
    ]);
    expect(shownFindings(p).map((f) => f.severity)).toEqual(["Critical", "High", "Low"]);
    expect(shownFindings(p)[0].title).toBe("open queue");
  });

  it("shows exploratory findings until triage has drafted defects, then only the defects", () => {
    const before = panels([ev(1, "exploratory", "finding", { severity: "Medium", title: "Medium: odd page" })]);
    expect(shownFindings(before).map((f) => f.kind)).toEqual(["finding"]);
    const after = foldPanels(before, [ev(2, "triage", "defect", { severity: "High", title: "High: crash" })]);
    expect(shownFindings(after).map((f) => f.kind)).toEqual(["defect"]);
  });

  it("keeps heals and the report", () => {
    const p = panels([ev(1, "healer", "heal", { title: "Use the new button name" }), ev(2, "reporter", "write", { title: "Report written" })]);
    expect(shownFindings(p).map((f) => f.kind).sort()).toEqual(["heal", "report"]);
  });
});

describe("rules, code and the document", () => {
  it("counts the Reconciler's statuses and lists its questions", () => {
    const p = panels([
      ev(1, "reconciler", "status", { status: "Confirmed", req: "FR-1", rule_kind: "max_length", field: "name" }),
      ev(2, "reconciler", "status", { status: "Divergent", req: "FR-2" }),
      ev(3, "reconciler", "status", { status: "Confirmed", req: "FR-3" }),
      ev(4, "reconciler", "question", { title: "Is the limit 50 or 100?" }),
    ]);
    expect(p.rules.counts).toEqual({ Confirmed: 2, Divergent: 1 });
    expect(p.rules.questions).toEqual(["Is the limit 50 or 100?"]);
    expect(p.rules.rows[0].req).toBe("FR-3");                 // newest first
  });

  it("keeps each generated file with its latest preview", () => {
    const p = panels([
      ev(1, "generator", "write", { file: "test_pages.py", tests: 3, preview: "def test_a(): ..." }),
      ev(2, "generator", "write", { file: "test_pages.py", tests: 4, preview: "def test_b(): ..." }),
    ]);
    expect(p.code.get("test_pages.py")).toEqual({ file: "test_pages.py", tests: 4, preview: "def test_b(): ..." });
  });

  it("builds the document from the Analyst's reading and adds the Writer's rewrites to each requirement", () => {
    const p = panels([
      ev(1, "srs", "open", { file: "SRS.docx", blocks: 33 }),
      ev(2, "srs", "heading", { title: "1. Users", level: 1 }),
      ev(3, "srs", "requirement", { req: "FR-1", text: "FR-1: The name allows 50 characters", flags: ["characters"] }),
      ev(4, "srs", "rule", { req: "FR-1", rule_kind: "max_length", field: "name", value: 50 }),
      ev(5, "srs", "ambiguity", { req: "FR-1", term: "quickly" }),
      ev(6, "writer", "requirement", { req: "FR-1", title: "FR-1: Applicant name accepts at most 50 characters", by: "rules" }),
    ]);
    const req = p.doc.requirements.get("FR-1");
    expect(req?.text).toBe("The name allows 50 characters");
    expect(req?.rules).toEqual(["max length · name 50"]);
    expect(req?.vague).toEqual(["quickly"]);
    expect(req?.rewrites).toEqual(["Applicant name accepts at most 50 characters"]);
    expect(p.doc.blocks.map((b) => b.kind)).toEqual(["file", "heading", "requirement"]);
  });
});

describe("lanes: one browser frame per worker", () => {
  it("keeps the newest screenshot, the outlined element, the address, role, case, last steps and verdict", () => {
    const events = [
      ev(1, "executor", "navigate", { w: "gw0", url: "http://127.0.0.1:8800/apply", role: "citizen", case: "TC-7", shot: "gw0-00001.jpg", box: { x: 1, y: 2, width: 3, height: 4 }, vw: 1280, vh: 720 }),
      ...Array.from({ length: 8 }, (_, i) => ev(2 + i, "executor", "action", { w: "gw0", title: `step ${i}` })),
      ev(20, "executor", "verdict", { w: "gw0", level: "bad", title: "DEFECT: name accepts 100 characters" }),
    ].map((e) => ({ ...e, w: String(e.w) }));
    const lanes = foldLanes(emptyLanes, events);
    const lane = lanes.lanes.get("gw0");
    expect(lane).toMatchObject({ url: "http://127.0.0.1:8800/apply", role: "citizen", case: "TC-7", shot: "gw0-00001.jpg" });
    expect(lane?.steps).toHaveLength(6);
    expect(lane?.verdict).toEqual({ level: "bad", text: "DEFECT: name accepts 100 characters" });
  });

  it("ignores agents that use no browser and drops a screenshot name that is not a plain file name", () => {
    const lanes = foldLanes(emptyLanes, [
      { ...ev(1, "srs", "rule"), w: "main" },
      { ...ev(2, "explorer", "navigate", { shot: "../../etc/passwd.jpg" }), w: "main" },
    ]);
    expect(lanes.order).toEqual(["main"]);
    expect(lanes.lanes.get("main")?.shot).toBeNull();
  });
});
