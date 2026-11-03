import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { stubFetch } from "../test-fetch";
import { Project } from "./Project";

const BUDGET = { month: "2026-11", spent: 0.42, cap: 10, pct: 4, alert_at_pct: 80, state: "ok" };

function mount(settings: unknown) {
  stubFetch({
    "GET /projects/demo": { slug: "demo", name: "Demo portal", url: "http://127.0.0.1:8800" },
    "GET /projects/demo/runs": [],
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
