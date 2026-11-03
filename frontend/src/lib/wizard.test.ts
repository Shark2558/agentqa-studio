import { describe, expect, it } from "vitest";
import { STEPS, answersForApi, canContinue, initialWizard, reduceWizard, rolesForApi, type WizardState } from "./wizard";

function withProject(): WizardState {
  let s = reduceWizard(initialWizard, { type: "field", field: "name", value: "UR Portal" });
  s = reduceWizard(s, { type: "field", field: "url", value: "https://ur.example" });
  return reduceWizard(s, { type: "created", slug: "ur-portal" });
}

describe("wizard reducer", () => {
  it("has six steps in the PRD's order", () => {
    expect(STEPS.map((s) => s.key)).toEqual(["basics", "requirements", "accounts", "ai", "schedule", "review"]);
  });

  it("step 1 needs a name and a web address, then the created project's slug", () => {
    expect(canContinue(initialWizard)).toBe(false);
    let s = reduceWizard(initialWizard, { type: "field", field: "name", value: "UR Portal" });
    s = reduceWizard(s, { type: "field", field: "url", value: "ftp://x" });
    expect(canContinue(s)).toBe(false);
    s = reduceWizard(s, { type: "field", field: "url", value: "https://ur.example" });
    expect(canContinue(s)).toBe(true);
    expect(s.slug).toBeNull();
    s = reduceWizard(s, { type: "created", slug: "ur-portal" });
    expect(s.slug).toBe("ur-portal");
  });

  it("step 2 needs at least one readable document or typed text", () => {
    let s = reduceWizard(withProject(), { type: "next" });
    expect(s.step).toBe(1);
    expect(canContinue(s)).toBe(false);
    s = reduceWizard(s, { type: "document", doc: { name: "SRS.docx", status: "read", detail: "", segments: 40, size: 1, kind: "docx", folder: "srs" } });
    expect(canContinue(s)).toBe(true);
    s = reduceWizard(s, { type: "removeDocument", name: "SRS.docx" });
    expect(canContinue(s)).toBe(false);
    s = reduceWizard(s, { type: "field", field: "typed", value: "The portal must send an SMS." });
    expect(canContinue(s)).toBe(true);
  });

  it("an unreadable document alone does not count", () => {
    let s = reduceWizard(withProject(), { type: "next" });
    s = reduceWizard(s, { type: "document", doc: { name: "scan.png", status: "unread", detail: "an image: no OCR", segments: 0, size: 1, kind: "png", folder: "srs" } });
    expect(canContinue(s)).toBe(false);
  });

  it("keeps the chat's questions and answers and marks the list confirmed", () => {
    let s = reduceWizard(withProject(), { type: "next" });
    s = reduceWizard(s, {
      type: "chat",
      chat: { source: "rules", items: [{ id: "T-001", text: "Reports can be exported.", kind: "requirement", flags: [] }],
        questions: [{ id: "q1", topic: "roles", question: "Who will use this?" }] },
    });
    expect(s.chat?.items).toHaveLength(1);
    s = reduceWizard(s, { type: "answer", id: "q1", answer: "Clerks." });
    expect(s.answers).toEqual({ q1: "Clerks." });
    expect(s.confirmed).toBe(false);
    s = reduceWizard(s, { type: "confirm" });
    expect(s.confirmed).toBe(true);
    s = reduceWizard(s, { type: "field", field: "typed", value: "changed" });   // editing the text re-opens the question
    expect(s.confirmed).toBe(false);
  });

  it("step 3 needs a role with a login button text, or no login", () => {
    let s = reduceWizard(withProject(), { type: "goto", step: 2 });
    expect(canContinue(s)).toBe(false);
    s = reduceWizard(s, { type: "role", index: 0, role: { role: "clerk", login_option: "Department Login", method: "password", username: "clerk1", password: "x" } });
    expect(canContinue(s)).toBe(true);
    s = reduceWizard(s, { type: "role", index: 0, role: { role: "", login_option: "", method: "password" } });
    expect(canContinue(s)).toBe(false);
    s = reduceWizard(s, { type: "field", field: "noLogin", value: true });
    expect(canContinue(s)).toBe(true);
  });

  it("roles are added and removed immutably, each with its own row key", () => {
    const before = reduceWizard(withProject(), { type: "goto", step: 2 });
    const added = reduceWizard(before, { type: "addRole" });
    expect(added.roles).toHaveLength(before.roles.length + 1);
    expect(before.roles).not.toBe(added.roles);
    expect(added.roles[0].uid).not.toBe(added.roles[1].uid);
    const removed = reduceWizard(added, { type: "removeRole", index: 0 });
    expect(removed.roles).toHaveLength(before.roles.length);
  });

  it("sends the API only filled rows without the row keys, and the answers with their topics", () => {
    let s = reduceWizard(withProject(), { type: "role", index: 0, role: { uid: "role-9", role: "clerk", login_option: "Dept", method: "password" } });
    s = reduceWizard(s, { type: "addRole" });
    expect(JSON.parse(JSON.stringify(rolesForApi(s)))).toEqual([{ role: "clerk", login_option: "Dept", method: "password" }]);
    s = reduceWizard(s, { type: "chat", chat: { source: "rules", items: [], questions: [{ id: "q1", topic: "roles", question: "Who?" }] } });
    s = reduceWizard(s, { type: "answer", id: "q1", answer: "Clerks." });
    expect(answersForApi(s)).toEqual([{ question: "Who?", answer: "Clerks.", topic: "roles" }]);
    expect(rolesForApi({ ...s, noLogin: true })).toEqual([]);
  });

  it("back and next stay inside the six steps", () => {
    let s = reduceWizard(withProject(), { type: "back" });
    expect(s.step).toBe(0);
    s = reduceWizard(s, { type: "goto", step: 5 });
    s = reduceWizard(s, { type: "next" });
    expect(s.step).toBe(5);
  });
});
