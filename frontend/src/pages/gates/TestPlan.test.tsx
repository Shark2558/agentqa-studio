import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { fail, sentBody } from "../../test-fetch";
import { demo, renderPage, type GatesDemo } from "../../test-fixtures/gates";
import { TestPlan } from "./TestPlan";

function waiting(d: GatesDemo): GatesDemo {
  d.plan.plan.approved = false;
  d.plan.plan.approved_at = null;
  return d;
}

const SHOWN = 30;      // the API pages by 200; 30 rows keep jsdom's accessible-name queries fast

function mount(d: GatesDemo, extra: Record<string, unknown> = {}, role = "owner") {
  const cases = { ...d.cases, items: d.cases.items.slice(0, SHOWN) };
  return renderPage(<TestPlan />, "/projects/demo/plan", "/projects/:slug/plan", {
    "GET /projects/demo/plan": d.plan, "GET /projects/demo/plan/cases": cases,
    "GET /projects/demo/gates": { ...d.gates, running: d.plan.running }, ...extra,
  }, role);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// The page renders the summary, 19 type rows, 23 chips and the cases: jsdom needs more than the default 5 s under load.
describe("Test plan page", { timeout: 20_000 }, () => {
  it("shows the summary, the gaps and a filter chip per case type with its count", async () => {
    mount(waiting(demo()));
    expect(await screen.findByText("30 of 35")).toBeInTheDocument();
    expect(screen.getByText("FR-11")).toBeInTheDocument();
    expect(screen.getByText(/no rejection or return action/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "functional (56)" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "All types (206)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByRole("checkbox", { name: /^Select TC-/ })).toHaveLength(SHOWN);
    expect(screen.getByRole("button", { name: "Show more" })).toBeInTheDocument();     // 30 of 206 shown
  });

  it("shows unread documents and cases skipped on production by name, as the API sends them (objects)", async () => {
    const d = waiting(demo());
    d.plan.gaps = { ...d.plan.gaps, unread: [{ name: "Scan.pdf", status: "unread", detail: "no text layer" }],
                    production: [{ key: "TC-0042", title: "Submit the payment form", path: "/pay" }] };
    mount(d);
    expect(await screen.findByText("Scan.pdf (no text layer)")).toBeInTheDocument();
    expect(screen.getByText("Not run on production: Submit the payment form")).toBeInTheDocument();
  });

  it("asks why before rejecting the selected cases, then sends one decision", async () => {
    const fetch = mount(waiting(demo()), { "POST /projects/demo/plan/cases": { changed: 1, plan: demo().plan.plan } }).fetch;
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select TC-0001" }));
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    const confirm = screen.getByRole("button", { name: "Reject 1 case" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: /Why/ }), { target: { value: "duplicate of TC-0002" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(sentBody(fetch, "POST", "/plan/cases")).toEqual({ ids: ["TC-0001"], decision: "reject", why: "duplicate of TC-0002" }));
  });

  it("approves every case of one type without a reason", async () => {
    const fetch = mount(waiting(demo()), { "POST /projects/demo/plan/types/a11y_basic": { changed: 15, plan: demo().plan.plan } }).fetch;
    fireEvent.click(await screen.findByRole("button", { name: "Approve every a11y_basic case" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/plan/types/a11y_basic")).toEqual({ decision: "approve", why: "" }));
  });

  it("offers the ready imported manual cases in one click", async () => {
    const d = waiting(demo());
    d.plan.imported = { ready: 9, review: 1, approved: 0, rejected: 0 };
    const fetch = mount(d, { "POST /projects/demo/plan/imported": { changed: 9, plan: d.plan.plan } }).fetch;
    fireEvent.click(await screen.findByRole("button", { name: "Approve the 9 ready imported cases" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/plan/imported")).toEqual({ ids: [], decision: "approve_ready", why: "" }));
  });

  it("approves the plan it shows, by its fingerprint, and says so when the plan changed meanwhile", async () => {
    const fetch = mount(waiting(demo()), { "POST /projects/demo/plan/approve": fail(409, "plan_changed", "x") }).fetch;
    fireEvent.click(await screen.findByRole("button", { name: "Approve the test plan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/plan changed/);
    expect(sentBody(fetch, "POST", "/plan/approve")).toEqual({ digest: "2db35a677bfb", why: "" });
  });

  it("keeps every decision off while a run is going", async () => {
    const d = waiting(demo());
    d.plan.running = true;
    mount(d);
    expect(await screen.findByRole("button", { name: "Approve the test plan" })).toBeDisabled();
    expect(screen.getByText(/A run is going/)).toBeInTheDocument();
  });

  it("after approval offers Generate and run, which continues the run and opens the Live View", async () => {
    const run = { id: 7, stage: "continue", status: "running", started_at: "", finished_at: null, exit_code: null };
    const fetch = mount(demo(), { "POST /projects/demo/runs": run }).fetch;
    expect(await screen.findByText(/Approved on/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve the test plan" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Generate and run" }));
    expect(await screen.findByTestId("landed")).toHaveTextContent("/projects/demo/live?session=job-7-continue");
    expect(sentBody(fetch, "POST", "/projects/demo/runs")).toEqual({ scope: "continue" });
  });

  it("follows the polled gate counts, so a finished run frees the decisions without a reload", async () => {
    const d = waiting(demo());
    d.plan.running = true;                                    // the plan was read while a run went
    mount(d, { "GET /projects/demo/gates": { ...d.gates, running: false } });
    const approve = await screen.findByRole("button", { name: "Approve the test plan" });
    await waitFor(() => expect(approve).toBeEnabled());
    expect(screen.queryByText(/A run is going/)).toBeNull();
  });

  it("selects every case shown with one box above the table, at every width", async () => {
    mount(waiting(demo()));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select every case shown" }));
    expect(screen.getByText(`${SHOWN} cases selected`)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select every case shown" }).closest("table")).toBeNull();
  });

  it("clears the selection when the filter changes, so no hidden case is decided", async () => {
    mount(waiting(demo()));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select TC-0001" }));
    expect(screen.getByText("1 case selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "functional (56)" }));
    expect(screen.queryByText("1 case selected")).toBeNull();
  });

  it("closes an open reason box when its selection is cleared", async () => {
    mount(waiting(demo()));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select TC-0001" }));
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear the selection" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("puts the decision bar after the cases it decides, in reading order", async () => {
    mount(waiting(demo()));
    const table = (await screen.findByRole("checkbox", { name: "Select TC-0001" })).closest("table");
    const bar = screen.getByRole("group", { name: "Decide the selected cases" });
    expect(table && table.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("says when the cases cannot be loaded, and when none match the filter", async () => {
    mount(waiting(demo()), { "GET /projects/demo/plan/cases": fail(500, "internal", "x") });
    expect(await screen.findByText("The cases could not be loaded. Reload the page.")).toBeInTheDocument();
    cleanup();
    mount(waiting(demo()), { "GET /projects/demo/plan/cases": { items: [], total: 0 } });
    expect(await screen.findByText("No cases match these filters.")).toBeInTheDocument();
  });

  it("announces the approval and keeps focus on the approval section", async () => {
    const d = waiting(demo());
    const approved = { ...d.plan.plan, approved: true, approved_at: "2026-11-04T11:00:00" };
    mount(d, { "POST /projects/demo/plan/approve": approved });
    fireEvent.click(await screen.findByRole("button", { name: "Approve the test plan" }));
    await waitFor(() => expect(screen.getByRole("status", { name: "Updates" })).toHaveTextContent("The test plan is approved."));
    expect(screen.getByRole("heading", { name: "Approval" })).toHaveFocus();
  });

  it("links the Excel download from the page itself", async () => {
    mount(demo());
    expect(await screen.findByRole("link", { name: /Download the test cases \(Excel\)/ })).toHaveAttribute(
      "href", "/api/v1/projects/demo/plan/testcases.xlsx");
  });

  it("a Viewer reads the plan and downloads it, with no controls", async () => {
    mount(waiting(demo()), {}, "viewer");
    expect(await screen.findByText("30 of 35")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
    // The status chips "Approved" / "Rejected" are filters, not decisions: only decision buttons must be absent.
    for (const name of ["Approve the test plan", "Approve", "Reject", "Generate and run", /^Approve every/, /^Reject every/]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.getByRole("link", { name: /Download the test cases/ })).toBeInTheDocument();
  });
});
