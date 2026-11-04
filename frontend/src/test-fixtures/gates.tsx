/** The gates' fixture (what the API answers for the owner's real No-AI demo, from tools/make_gates_fixture.py) and a
 *  helper that mounts one page at its route, signed in with a role, with the fetch stub answering. */
import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { stubFetch, type Routes as Stubs } from "../test-fetch";
import type {
  ChangesPage, DefectsView, GateCounts, Page, PlanView, QuestionsView, RequirementsPage, TestCase,
} from "../lib/gatesApi";
import fixture from "./gates-demo.json";

export interface GatesDemo {
  gates: GateCounts;
  questions: QuestionsView;
  plan: PlanView;
  cases: Page<TestCase>;
  defects: DefectsView;
  requirements: RequirementsPage;
  changes: ChangesPage;
}

/** A fresh deep copy each time, so a test that edits its copy cannot leak into the next one. */
export function demo(): GatesDemo {
  return structuredClone(fixture) as unknown as GatesDemo;
}

export const OWNER = "owner@example.com";

function Landed() {
  const location = useLocation();
  return <p data-testid="landed">{location.pathname + location.search}</p>;
}

/** Mount `element` at `path` (matched by `pattern`); every other address shows where the app navigated to. */
export function renderPage(element: ReactElement, path: string, pattern: string, routes: Stubs, role = "owner") {
  const fetch = stubFetch({ "GET /auth/me": { email: role === "owner" ? OWNER : `${role}@example.com`, role }, ...routes });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={pattern} element={element} />
          <Route path="*" element={<Landed />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { fetch, client, ...view };
}
