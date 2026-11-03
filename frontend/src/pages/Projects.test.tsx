import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { stubFetch } from "../test-fetch";
import { Projects } from "./Projects";
import { NewProject } from "./wizard/NewProject";

function mount(role: string, path = "/") {
  stubFetch({ "GET /auth/me": { email: "o@example.com", role }, "GET /projects": [] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={<Projects />} />
          <Route path="/projects/new" element={<NewProject />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Projects: who may create and run", () => {
  it("offers the owner the demo and a new project", async () => {
    mount("owner");
    expect(await screen.findByRole("button", { name: /Try the demo/ })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /New project/ }).length).toBeGreaterThan(0);
  });

  it("a Viewer is offered neither, not even in the empty list", async () => {
    mount("viewer");
    expect(await screen.findByText(/No projects yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Try the demo/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /New project/ })).toBeNull();
  });

  it("a Viewer who opens the wizard's address is told they can watch and read, with no form to fill", async () => {
    mount("viewer", "/projects/new");
    expect(await screen.findByText(/Viewers can watch runs and read results/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run full pipeline/ })).toBeNull();
  });
});
