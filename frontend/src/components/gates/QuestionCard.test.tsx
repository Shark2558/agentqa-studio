import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import type { Question } from "../../lib/gatesApi";
import { fail, sentBody } from "../../test-fetch";
import { demo, renderPage } from "../../test-fixtures/gates";
import { QuestionCard } from "./QuestionCard";

const ANSWER = "POST /projects/demo/questions/1/answer";

function mount(q: Question, routes: Record<string, unknown> = {}, mayWrite = true, onDone = vi.fn()) {
  const view = renderPage(<QuestionCard slug="demo" question={q} mayWrite={mayWrite} onDone={onDone} />, "/q", "/q", routes);
  return { ...view, onDone };
}

const first = (): Question => demo().questions.items[0];      // srs_only_field: option 1 asks for a value
const answered = (): Question => ({ ...first(), status: "answered", answer: "Not applicable: drop the rule", choice: 2, answered_at: "2026-11-04T10:00:00" });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("QuestionCard", () => {
  it("asks for a value only when the chosen option needs one, and says so instead of saving without it", () => {
    const { fetch } = mount(first());
    expect(screen.getByRole("radiogroup", { name: /Remarks/ })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /Your value/ })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: /Exists under another name/ }));
    expect(screen.getByRole("textbox", { name: /Your value/ })).toBeRequired();
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
    expect(screen.getByText("Enter the value this option asks for.")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining("/answer"), expect.anything());
    fireEvent.click(screen.getByRole("radio", { name: /Missing from the app/ }));
    expect(screen.queryByRole("textbox", { name: /Your value/ })).toBeNull();
  });

  it("says an answer no stage reads yet is a note for checking by hand, open or answered (sitting 1, S1)", () => {
    const vague = demo().questions.items.find((q) => q.note_only);
    if (!vague) throw new Error("the fixture has note-only questions");
    const NOTE = /kept as a note for checking by hand/;
    mount(vague);
    expect(screen.getByText(/^Your answer is kept as a note/)).toBeInTheDocument();
    expect(screen.getByRole("radiogroup")).toHaveAccessibleDescription(NOTE);    // read with the options, not only above them
    cleanup();
    mount(vague, {}, false);                                                        // a Viewer answers nothing: no "Your"
    expect(screen.getByText(/^An answer to this question is kept as a note/)).toBeInTheDocument();
    cleanup();
    mount({ ...vague, status: "answered", answer: "Enter a precise rule", choice: 1, value: "3 seconds", answered_at: "2026-11-04T10:00:00" });
    expect(screen.getByText(NOTE)).toBeInTheDocument();
    cleanup();
    mount(first());
    expect(screen.queryByText(NOTE)).toBeNull();
  });

  it("says an option must be chosen first", () => {
    mount(first());
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
    expect(screen.getByText("Choose one of the options first.")).toBeInTheDocument();
  });

  it("sends the choice and the value, then tells the page", async () => {
    const saved = { ...first(), status: "answered", answer: "Exists under another name: enter it", choice: 1, value: "Comments" };
    const { fetch, onDone } = mount(first(), { [ANSWER]: saved });
    fireEvent.click(screen.getByRole("radio", { name: /Exists under another name/ }));
    fireEvent.change(screen.getByRole("textbox", { name: /Your value/ }), { target: { value: "Comments" } });
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/questions/1/answer")).toEqual({ choice: 1, value: "Comments" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith("Answer saved."));
  });

  it("sends no value for an option that does not ask for one, even after one was typed", async () => {
    const { fetch } = mount(first(), { [ANSWER]: { ...first(), status: "answered" } });
    fireEvent.click(screen.getByRole("radio", { name: /Exists under another name/ }));
    fireEvent.change(screen.getByRole("textbox", { name: /Your value/ }), { target: { value: "Comments" } });
    fireEvent.click(screen.getByRole("radio", { name: /Missing from the app/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/questions/1/answer")).toEqual({ choice: 0, value: "" }));
  });

  it("says so when someone else already answered (409)", async () => {
    mount(first(), { [ANSWER]: fail(409, "not_open", "Question 1 is no longer open") });
    fireEvent.click(screen.getByRole("radio", { name: /Missing from the app/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already answered/);
  });

  it("shows a question from the documents as text, never as markup", () => {
    const { container } = mount({ ...first(), question: "<img src=x onerror=alert(1)> is the field there?" });
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x onerror=alert\(1\)> is the field there\?/)).toBeInTheDocument();
  });

  it("an answered question can be reopened only with a reason", async () => {
    const { fetch, onDone } = mount(answered(), { "POST /projects/demo/questions/1/reopen": { ...first() } });
    expect(screen.getByText(/Not applicable: drop the rule/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reopen question 1" }));
    const confirm = screen.getByRole("button", { name: "Reopen the question" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: /Why/ }), { target: { value: "  wrong choice " } });
    fireEvent.click(confirm);
    await waitFor(() => expect(sentBody(fetch, "POST", "/questions/1/reopen")).toEqual({ why: "wrong choice" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith("Question reopened."));
  });

  it("Escape closes the reason box and puts focus back on the button that opened it", () => {
    mount(answered());
    const reopen = screen.getByRole("button", { name: "Reopen question 1" });
    fireEvent.click(reopen);
    const box = screen.getByRole("textbox", { name: /Why/ });
    expect(box).toHaveFocus();
    fireEvent.keyDown(box, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(reopen).toHaveFocus();
  });

  it("a Viewer reads the question and its options but gets no controls", () => {
    mount(first(), {}, false);
    expect(screen.getByText(/Remarks/)).toBeInTheDocument();
    expect(screen.getByText("Missing from the app (log a defect)")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
