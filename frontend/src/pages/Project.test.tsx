import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { sentBody, stubFetch } from "../test-fetch";
import { demo } from "../test-fixtures/gates";
import { Project } from "./Project";

const BUDGET = { month: "2026-11", spent: 0.42, cap: 10, pct: 4, alert_at_pct: 80, state: "ok" };
const GATES = demo().gates;
const RUN = { id: 3, stage: "pipeline", status: "running", started_at: "", finished_at: null, exit_code: null };

function mount(settings: unknown, role = "owner", gates = GATES) {
  const fetch = stubFetch({
    "GET /auth/me": { email: "o@example.com", role },
    "GET /projects/demo": { slug: "demo", name: "Demo portal", url: "http://127.0.0.1:8800" },
    "GET /projects/demo/runs": [],
    "POST /projects/demo/runs": RUN,
    "GET /projects/demo/gates": gates,
    "GET /projects/demo/ai": { settings, effective: [], notice: null, budget: BUDGET },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/projects/demo"]}>
        <Routes>
          <Route path="/projects/:slug" element={<Project />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { fetch };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Project page: the AI card", () => {
  it("shows No AI and no spend for a project without an ai block, and links to the AI page", async () => {
    mount({});
    expect(await screen.findByText("No AI")).toBeInTheDocument();
    expect(screen.getByText("nothing is spent")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /AI: No AI/ })).toHaveAttribute("href", "/projects/demo/ai");
  });

  it("shows the month's spend for a Cloud project", async () => {
    mount({ mode: "cloud" });
    expect(await screen.findByText("Cloud AI")).toBeInTheDocument();
    expect(screen.getByText("$0.42 of $10.00 used this month")).toBeInTheDocument();
  });
});

describe("Project page: who may start a run", () => {
  it("offers the owner the Run button and the demo switch, off by default and named for what it does (decision 3)", async () => {
    mount({});
    expect(await screen.findByRole("button", { name: /Run full pipeline/ })).toBeInTheDocument();
    const auto = screen.getByRole("checkbox", { name: "Approve the test plan automatically (demos)" });
    expect(auto).not.toBeChecked();
    expect(screen.getByText(/only approves the test plan/)).toBeInTheDocument();
  });

  it("starts a run that waits at the plan gate unless the switch is ticked", async () => {
    const fetch = mount({}).fetch;
    fireEvent.click(await screen.findByRole("button", { name: /Run full pipeline/ }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/projects/demo/runs")).toMatchObject({ scope: "pipeline", auto_approve: false }));
  });

  it("a Viewer sees no Run button and no switch", async () => {
    mount({}, "viewer");
    expect(await screen.findByText("No AI")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run full pipeline/ })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /Approve the test plan/ })).toBeNull();
    expect(screen.getByText(/^Nothing has run yet\.$/)).toBeInTheDocument();
  });
});

describe("Project page: what needs you", () => {
  it("lists what waits for a person, each with a link to its page", async () => {
    mount({});
    const card = await screen.findByRole("region", { name: "What needs you" });
    expect(await within(card).findByRole("link", { name: "15 questions to answer" })).toHaveAttribute("href", "/projects/demo/questions");
    expect(within(card).getByRole("link", { name: "19 defects to confirm or reject" })).toHaveAttribute("href", "/projects/demo/defects");
  });

  it("speaks to a Viewer about what is waiting, not what needs them (sitting 1, S5)", async () => {
    mount({}, "viewer");
    const card = await screen.findByRole("region", { name: "What is waiting" });
    expect(await within(card).findByRole("link", { name: "15 open questions" })).toHaveAttribute("href", "/projects/demo/questions");
    expect(within(card).getByRole("link", { name: "19 defects waiting for a decision" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "What needs you" })).toBeNull();
  });

  it("says so when nothing waits", async () => {
    mount({}, "owner", { ...GATES, questions_open: 0, defects_draft: 0 });
    expect(await screen.findByText("Nothing needs you right now.")).toBeInTheDocument();
  });
});
