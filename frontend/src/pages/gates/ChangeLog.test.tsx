import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { demo, renderPage } from "../../test-fixtures/gates";
import { ChangeLog } from "./ChangeLog";

const PERSON = { id: 9, at: "2026-11-04T11:00:00", agent: "person", object: "case", object_id: "TC-0003", change: "rejected 1 case(s): TC-0003", why: "duplicate", by: "owner@example.com (owner)" };

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Change log page", () => {
  it("shows who made each change and why", async () => {
    const agents = demo().changes.items[0];
    renderPage(<ChangeLog />, "/projects/demo/changes", "/projects/:slug/changes", {
      "GET /projects/demo/changes": { items: [PERSON, agents], next_before: null },
    });
    expect(await screen.findByText("owner@example.com (owner)")).toBeInTheDocument();
    expect(screen.getByText("duplicate")).toBeInTheDocument();
    expect(screen.getByText("rejected 1 case(s): TC-0003")).toBeInTheDocument();
    expect(screen.getByText("AgentQA's agents")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show older" })).toBeNull();
  });

  it("shows an answer's question as the question, not as a reason (sitting 1, S3)", async () => {
    const answer = { ...PERSON, id: 10, object: "question", object_id: "9", change: "answered 'Enter a precise rule' (3 s) for NFR-01",
                     why: "NFR-01 is not testable as written" };
    renderPage(<ChangeLog />, "/projects/demo/changes", "/projects/:slug/changes", {
      "GET /projects/demo/changes": { items: [answer, PERSON], next_before: null },
    });
    const asked = await screen.findByText("NFR-01 is not testable as written");
    expect(asked.closest("td")).toHaveTextContent(/^The question: NFR-01 is not testable as written$/);
    expect(screen.getByText("duplicate").closest("td")).toHaveTextContent(/^duplicate$/);
  });

  it("pages back with Show older", async () => {
    let calls = 0;
    const older = { ...PERSON, id: 4, change: "answered question 2", why: "" };
    const { fetch } = renderPage(<ChangeLog />, "/projects/demo/changes", "/projects/:slug/changes", {
      "GET /projects/demo/changes": () => (calls++ === 0 ? { items: [PERSON], next_before: 9 } : { items: [older], next_before: null }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Show older" }));
    expect(await screen.findByText("answered question 2")).toBeInTheDocument();
    await waitFor(() => expect(String(fetch.mock.calls.at(-1)?.[0])).toContain("before=9"));
    expect(screen.queryByRole("button", { name: "Show older" })).toBeNull();
  });
});
