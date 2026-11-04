import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { fail } from "../../test-fetch";
import { demo, renderPage } from "../../test-fixtures/gates";
import { Questions } from "./Questions";

function mount(over: { answered?: number; policy?: string; source?: "run" | "project"; running?: boolean } = {}, extra: Record<string, unknown> = {}, role = "owner") {
  const d = demo();
  d.questions.counts.answered = over.answered ?? 0;
  if (over.policy) d.questions.policy.divergence = over.policy;
  if (over.source) d.questions.policy.source = over.source;
  d.gates.running = over.running ?? false;
  return renderPage(<Questions />, "/projects/demo/questions", "/projects/:slug/questions", {
    "GET /projects/demo/questions": d.questions, "GET /projects/demo/gates": d.gates, ...extra,
  }, role);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Questions page", () => {
  it("shows the counts, every open question and the policy a re-plan will use", async () => {
    mount();
    expect(await screen.findByText("15 open · 0 answered")).toBeInTheDocument();
    expect(screen.getAllByRole("radiogroup")).toHaveLength(15);
    expect(screen.getByText(/this project's rule from project.yaml: it asks you whenever the requirements and the application disagree/)).toBeInTheDocument();
  });

  it("says a re-plan reuses the rule of the run that made the plan (the owner's decision)", async () => {
    mount({ policy: "srs_wins", source: "run" });
    const note = await screen.findByText(/the rule this plan was made with: the requirements document wins whenever the two disagree/);
    expect(note).not.toHaveTextContent(/project\.yaml/);
  });

  it("applies the answers only once one is given, then links to the re-plan in the Live View", async () => {
    mount({ answered: 2 }, { "POST /projects/demo/questions/apply": { id: 12, stage: "replan", status: "running", started_at: "", finished_at: null, exit_code: null } });
    const apply = await screen.findByRole("button", { name: "Apply my answers and re-plan" });
    await waitFor(() => expect(apply).toBeEnabled());
    fireEvent.click(apply);
    const link = await screen.findByRole("link", { name: /Watch the re-plan/ });
    expect(link).toHaveAttribute("href", "/projects/demo/live?session=job-12-replan");
  });

  it("keeps Apply off with no answer yet and while a run is going, and says why a busy server refused", async () => {
    mount();
    expect(await screen.findByRole("button", { name: "Apply my answers and re-plan" })).toBeDisabled();
    cleanup();
    mount({ answered: 1, running: true });
    expect(await screen.findByText(/A run is going/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply my answers and re-plan" })).toBeDisabled();
    cleanup();
    mount({ answered: 1 }, { "POST /projects/demo/questions/apply": fail(409, "busy", "A stage is already running") });
    const apply = await screen.findByRole("button", { name: "Apply my answers and re-plan" });
    await waitFor(() => expect(apply).toBeEnabled());
    fireEvent.click(apply);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/run is going/));
  });

  it("announces a saved answer and moves focus to the list's heading, since the card leaves the list", async () => {
    mount({}, { "POST /projects/demo/questions/1/answer": { ...demo().questions.items[0], status: "answered" } });
    const card = (await screen.findAllByRole("article"))[0];
    fireEvent.click(within(card).getByRole("radio", { name: /Missing from the app/ }));
    fireEvent.click(within(card).getByRole("button", { name: "Save answer" }));
    await waitFor(() => expect(screen.getByRole("status", { name: "Updates" })).toHaveTextContent("Answer saved."));
    expect(screen.getByRole("heading", { name: "Open questions" })).toHaveFocus();
  });

  it("a Viewer reads the questions but has no Apply button", async () => {
    mount({ answered: 2 }, {}, "viewer");
    expect(await screen.findByText("15 open · 2 answered")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("radio")).toBeNull());
    expect(screen.queryByRole("button", { name: /Apply/ })).toBeNull();
  });
});
