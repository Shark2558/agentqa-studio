import { describe, expect, it } from "vitest";
import { demoBoard } from "../../test-fixtures/live";
import { cardModel, counterText, displayState, emptyBoard, foldBoard, type BoardModel } from "./board";
import { eventKey, toEvent, type LiveEvent } from "./event";

let seq = 0;
function ev(t: number, agent: string, kind: string, extra: Record<string, unknown> = {}): LiveEvent {
  seq += 1;
  const phase = kind === "stage_start" || kind === "stage_end" || kind === "stage_skip" ? "lifecycle" : "result";
  return toEvent({ t, seq, w: "main", agent, kind, title: `${agent} ${kind}`, phase, ...extra }) as LiveEvent;
}
const run = (events: LiveEvent[]): BoardModel => foldBoard(emptyBoard(demoBoard), events, demoBoard);
const card = (b: BoardModel, agent: string) => {
  const c = b.cards.get(agent);
  if (!c) throw new Error(`no card for ${agent}`);
  return c;
};

describe("board: the twelve stages in pipeline order", () => {
  it("starts with every stage queued, in the board's order", () => {
    const b = emptyBoard(demoBoard);
    expect(b.order).toEqual(demoBoard.stages.map((s) => s.agent));
    expect([...b.cards.values()].every((c) => c.state === "queued")).toBe(true);
    expect(card(b, "writer").label).toBe("Requirement Writer");
  });

  it("moves a stage from running to done and keeps when it started and ended", () => {
    const b = run([ev(10, "srs", "stage_start", { stage: "analyze" }), ev(22, "srs", "stage_end", { stage: "analyze" })]);
    expect(card(b, "srs")).toMatchObject({ state: "done", startedAt: 10, endedAt: 22 });
    expect(b.running).toBeNull();
  });

  it("says a stage failed, with the kind of error only", () => {
    const b = run([ev(1, "explorer", "stage_start"), ev(2, "explorer", "stage_end", { level: "bad", error: "RuntimeError" })]);
    expect(card(b, "explorer")).toMatchObject({ state: "failed", error: "RuntimeError" });
  });

  it("says a stage was skipped, and why", () => {
    const b = run([ev(1, "exploratory", "stage_skip", { stage: "exploratory", why: "exploratory.enabled is false" })]);
    expect(card(b, "exploratory")).toMatchObject({ state: "skipped", skipWhy: "exploratory.enabled is false" });
  });
});

describe("board: waiting for a person", () => {
  it("waits while an assist is open and goes back to running when it is answered", () => {
    const opened = run([ev(1, "explorer", "stage_start"), ev(2, "explorer", "assist", { assist_id: "a1", title: "Waiting for you: OTP?" })]);
    expect(card(opened, "explorer").state).toBe("waiting");
    const answered = foldBoard(opened, [ev(3, "explorer", "assist", { assist_id: "a1", title: "Thanks, continuing", level: "ok" })], demoBoard);
    expect(card(answered, "explorer").state).toBe("running");
  });

  it("keeps waiting until every open question of that agent is answered", () => {
    const b = run([
      ev(1, "explorer", "stage_start"),
      ev(2, "explorer", "assist", { assist_id: "a1" }),
      ev(3, "explorer", "assist", { assist_id: "a2" }),
      ev(4, "explorer", "assist", { assist_id: "a1", level: "ok" }),
    ]);
    expect(card(b, "explorer").state).toBe("waiting");
  });

  it("a stop at the plan gate leaves the Script Generator waiting for you and later stages not reached", () => {
    const b = run([
      ev(1, "designer", "stage_start"),
      ev(2, "designer", "stage_end"),
      ev(3, "pipeline", "gate", { title: "Stopped at the plan gate: a QA lead must approve the test plan", level: "warn" }),
    ]);
    expect(b.gates.plan).toBe("waiting");
    expect(displayState(card(b, "generator"), b, true)).toBe("waiting");
    expect(displayState(card(b, "executor"), b, true)).toBe("not-reached");
    expect(displayState(card(b, "designer"), b, true)).toBe("done");
  });

  it("an approved plan shows green", () => {
    expect(run([ev(1, "designer", "approve", { level: "ok" })]).gates.plan).toBe("approved");
  });
});

describe("board: gates and counters", () => {
  it("questions do not make the Reconciler wait: it is done, with the number of questions for you", () => {
    const qs = Array.from({ length: 15 }, (_, i) => ev(2 + i * 0.01, "reconciler", "question"));
    const b = run([ev(1, "reconciler", "stage_start"), ...qs, ev(3, "reconciler", "stage_end")]);
    expect(card(b, "reconciler").state).toBe("done");
    expect(b.gates.questions).toBe(15);
    expect(counterText(card(b, "reconciler"))).toContain("15 questions");
  });

  it("counts defects for the defects gate", () => {
    const b = run([ev(1, "triage", "defect"), ev(2, "triage", "defect")]);
    expect(b.gates.defects).toBe(2);
  });

  it("an agent without counters still says how many events it sent", () => {
    const b = run([ev(1, "healer", "stage_start"), ev(2, "healer", "observe")]);
    expect(counterText(card(b, "healer"))).toMatch(/event/);
  });
});

describe("board: helpers, models and costs belong to the stage running at the time", () => {
  it("the Functional Test Analyst's work counts for the Writer during write and for the Designer during design", () => {
    const b = run([
      ev(1, "writer", "stage_start"),
      ev(2, "analyst", "summary"),
      ev(3, "writer", "stage_end"),
      ev(4, "designer", "stage_start"),
      ev(5, "analyst", "summary"),
      ev(6, "casegen", "summary"),
    ]);
    expect(card(b, "writer").helpers).toEqual(["analyst"]);
    expect(card(b, "designer").helpers).toEqual(["analyst", "casegen"]);
    expect(b.cards.has("analyst")).toBe(false);
  });

  it("the Test Importer between stages counts for the Test Designer", () => {
    expect(card(run([ev(1, "importer", "summary")]), "designer").helpers).toEqual(["importer"]);
  });

  it("puts each model call's cost and model on the running stage and adds up the run's total", () => {
    const b = run([
      ev(1, "srs", "stage_start"),
      ev(2, "ai", "model", { agent_key: "documents", reason: "AI is off for this project" }),
      ev(3, "ai", "cost", { agent_key: "srs", model: "claude-sonnet-5-5", cost_usd: 0.0052, input_tokens: 1650, output_tokens: 190 }),
      ev(4, "srs", "stage_end"),
      ev(5, "explorer", "stage_start"),
      ev(6, "ai", "model", { agent_key: "login", reason: "AI is off for this project" }),
    ]);
    expect(card(b, "srs")).toMatchObject({ cost: 0.0052, actualModel: "claude-sonnet-5-5", tokensIn: 1650, tokensOut: 190 });
    expect(cardModel(card(b, "srs"))).toBe("claude-sonnet-5-5");
    expect(cardModel(card(b, "explorer"))).toBe("no AI: AI is off for this project");
    expect(b.ai).toEqual({ calls: 1, cost: 0.0052, tokensIn: 1650, tokensOut: 190 });
  });

  it("ignores a cost that is not a finite number", () => {
    const b = run([ev(1, "srs", "stage_start"), ev(2, "ai", "cost", { cost_usd: "free", model: "m" })]);
    expect(card(b, "srs").cost).toBe(0);
  });
});

const cost = (t: number, model: string, usd = 0) => ev(t, "ai", "cost", { agent_key: "req_writer", model, cost_usd: usd });
const switched = (t: number) => ev(t, "ai", "switched", { agent_key: "req_writer", from_provider: "anthropic", to_provider: "gemini", failure: "billing" });

describe("board: every model a card used, and the provider switches (C4)", () => {
  it("lists each model once, in the order first used, where the last one used is only one of them", () => {
    const b = run([ev(1, "writer", "stage_start"), cost(2, "claude-opus-5-5", 0.12), cost(3, "claude-opus-5-5", 0.11), switched(4),
                   cost(5, "gemini-flash-lite-latest", 0.001), cost(6, "claude-opus-5-5")]);
    expect(card(b, "writer").models).toEqual(["claude-opus-5-5", "gemini-flash-lite-latest"]);
    expect(card(b, "writer").actualModel).toBe("claude-opus-5-5");
    expect(cardModel(card(b, "writer"))).toBe("claude-opus-5-5, gemini-flash-lite-latest");
  });

  it("names two models and says how many more", () => {
    const used = (names: string[]) => card(run([ev(1, "srs", "stage_start"), ...names.map((m, i) => cost(2 + i, m))]), "srs");
    expect(cardModel(used(["a"]))).toBe("a");
    expect(cardModel(used(["a", "b", "c"]))).toBe("a, b and 1 more");
    expect(cardModel(used(["a", "b", "c", "d"]))).toBe("a, b and 2 more");
  });

  it("keeps the first 20 model names, however many the stream invents", () => {
    const b = run([ev(1, "srs", "stage_start"), ...Array.from({ length: 25 }, (_, i) => cost(2 + i, `m${i}`))]);
    expect(card(b, "srs").models).toHaveLength(20);
    expect(card(b, "srs").models.at(-1)).toBe("m19");
    expect(cardModel(card(b, "srs"))).toBe("m0, m1 and 18 more");
  });

  it("a cost line without a model leaves the models as they were", () => {
    const b = run([ev(1, "srs", "stage_start"), cost(2, "claude-sonnet-5-5"), ev(3, "ai", "cost", { cost_usd: 0.01 })]);
    expect(card(b, "srs").models).toEqual(["claude-sonnet-5-5"]);
    expect(card(b, "srs").actualModel).toBe("claude-sonnet-5-5");
  });

  it("cuts a very long model name to fit the card", () => {
    const b = run([ev(1, "srs", "stage_start"), cost(2, "x".repeat(200))]);
    expect(cardModel(card(b, "srs"))).toBe(`${"x".repeat(59)}…`);
  });

  it("credits a switch line to the stage running at its time, and to no card before any stage", () => {
    const early = switched(1);
    const during = switched(3);
    const b = run([early, ev(2, "writer", "stage_start"), during, ev(4, "writer", "stage_end"), ev(5, "designer", "stage_start")]);
    expect([...card(b, "writer").switchLines]).toEqual([eventKey(during)]);
    expect(card(b, "srs").switchLines.size).toBe(0);
    expect(card(b, "designer").switchLines.size).toBe(0);
    expect(b.ai.calls).toBe(0);                                  // a switch is not a billed call
  });

  it("keeps the first 50 switch lines on a card (the rest still show in What is happening)", () => {
    const lines = Array.from({ length: 60 }, (_, i) => switched(2 + i));
    const kept = card(run([ev(1, "writer", "stage_start"), ...lines]), "writer").switchLines;
    expect(kept.size).toBe(50);
    expect(kept.has(eventKey(lines[0])) && kept.has(eventKey(lines[49])) && !kept.has(eventKey(lines[50]))).toBe(true);
  });

  it("never changes the card it was given", () => {
    const before = run([ev(1, "writer", "stage_start"), cost(2, "a"), switched(3)]);
    const models = [...card(before, "writer").models];
    const lines = [...card(before, "writer").switchLines];
    foldBoard(before, [cost(4, "b"), switched(5)], demoBoard);
    expect(card(before, "writer").models).toEqual(models);
    expect([...card(before, "writer").switchLines]).toEqual(lines);
  });
});

describe("board: honest endings", () => {
  it("a stage outside this run's list is 'not in this run'", () => {
    const b = run([ev(1, "pipeline", "stage_start", { stages: ["run", "exploratory", "security", "triage", "heal", "report"] })]);
    expect(displayState(card(b, "srs"), b, false)).toBe("not-in-run");
    expect(displayState(card(b, "executor"), b, false)).toBe("queued");
  });

  it("a stage that started and never ended did not finish once the run is over", () => {
    const b = run([ev(1, "executor", "stage_start")]);
    expect(displayState(card(b, "executor"), b, false)).toBe("running");
    expect(displayState(card(b, "executor"), b, true)).toBe("did-not-finish");
  });

  it("the pipeline's own end is kept", () => {
    const b = run([ev(9, "pipeline", "stage_end", { outcome: "finished", level: "ok" })]);
    expect(b.ended).toEqual({ outcome: "finished", level: "ok" });
  });

  it("an agent the board does not know gets its own card after the stages", () => {
    const b = run([ev(1, "doctor", "start"), ev(2, "__proto__", "observe")]);
    expect(b.order.slice(-2)).toEqual(["doctor", "__proto__"]);
    expect(card(b, "doctor").label).toBe("Readiness check");
    expect(card(b, "__proto__").label).toBe("__proto__");
  });

  it("never changes the board it was given", () => {
    const before = emptyBoard(demoBoard);
    const copy = JSON.stringify([...before.cards.entries()]);
    foldBoard(before, [ev(1, "srs", "stage_start"), ev(2, "ai", "cost", { cost_usd: 1, model: "m" })], demoBoard);
    expect(JSON.stringify([...before.cards.entries()])).toBe(copy);
  });
});

describe("board: numbers from the run are kept in range (security review)", () => {
  it("a negative cost or token count never lowers the spend shown", () => {
    const b = run([ev(1, "srs", "stage_start"), ev(2, "ai", "cost", { cost_usd: 0.5, input_tokens: 10 }), ev(3, "ai", "cost", { cost_usd: -9, input_tokens: -100 })]);
    expect(b.ai.cost).toBe(0.5);
    expect(b.ai.tokensIn).toBe(10);
  });

  it("makes at most 40 cards, however many agent names the stream invents", () => {
    const b = run(Array.from({ length: 300 }, (_, i) => ev(i, "made-up-" + i, "note")));
    expect(b.cards.size).toBeLessThanOrEqual(40);
  });
});
