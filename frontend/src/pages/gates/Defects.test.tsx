import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { sentBody } from "../../test-fetch";
import { demo, renderPage } from "../../test-fixtures/gates";
import { Defects } from "./Defects";

const DECIDE = "POST /projects/demo/defects/decisions";

function mount(extra: Record<string, unknown> = {}, role = "owner") {
  const d = demo();
  return renderPage(<Defects />, "/projects/demo/defects", "/projects/:slug/defects", {
    "GET /projects/demo/defects": d.defects, "GET /projects/demo/gates": d.gates, ...extra,
  }, role);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Defects page", () => {
  it("counts open defects by severity, most severe first", async () => {
    mount();
    const list = await screen.findByRole("list", { name: "Open defects by severity" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["3 Critical", "6 High", "7 Medium", "3 Low"]);
    expect(screen.getAllByRole("article")).toHaveLength(19);
  });

  it("confirms several defects at once without a reason", async () => {
    const fetch = mount({ [DECIDE]: { changed: 2 } }).fetch;
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select DEF-001" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select DEF-002" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/defects/decisions")).toEqual({ ids: ["DEF-001", "DEF-002"], decision: "confirmed", why: "" }));
  });

  it("selects every defect shown with one box, and decides them together (sitting 1, S2)", async () => {
    const fetch = mount({ [DECIDE]: { changed: 19 } }).fetch;
    const all = await screen.findByRole("checkbox", { name: "Select the 19 defects shown" });
    fireEvent.click(all);
    for (const box of screen.getAllByRole("checkbox", { name: /^Select DEF-/ })) expect(box).toBeChecked();
    expect(all).toBeChecked();
    expect(screen.getByText("19 defects selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/defects/decisions")).toEqual(expect.objectContaining({
      ids: expect.arrayContaining(["DEF-001", "DEF-019"]), decision: "confirmed",
    })));
    expect((sentBody(fetch, "POST", "/defects/decisions") as { ids: string[] }).ids).toHaveLength(19);
  });

  it("unticking the box clears the selection", async () => {
    mount();
    const all = await screen.findByRole("checkbox", { name: "Select the 19 defects shown" });
    fireEvent.click(all);
    fireEvent.click(all);
    for (const box of screen.getAllByRole("checkbox", { name: /^Select DEF-/ })) expect(box).not.toBeChecked();
    expect(screen.queryByText(/defects? selected/)).toBeNull();
  });

  it("leaves out a defect already sent to a tracker, which cannot be decided again", async () => {
    const d = demo().defects;
    const items = d.items.map((x, i) => (i === 1 ? { ...x, status: "exported", external_key: "QA-12" } : x));
    const fetch = mount({ "GET /projects/demo/defects": { ...d, items }, [DECIDE]: { changed: 18 } }).fetch;
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select the 18 defects shown" }));
    expect(screen.getByText("18 defects selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/defects/decisions")).toBeDefined());
    const sent = (sentBody(fetch, "POST", "/defects/decisions") as { ids: string[] }).ids;
    expect(sent).toHaveLength(18);
    expect(sent).not.toContain(items[1].id);
  });

  it("announces the decision and keeps the bar after the defects in reading order", async () => {
    mount({ [DECIDE]: { changed: 2 } });
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select DEF-001" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select DEF-002" }));
    const bar = screen.getByRole("group", { name: "Decide the selected defects" });
    const lastCard = screen.getAllByRole("article").at(-1);
    expect(lastCard && lastCard.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByRole("status", { name: "Updates" })).toHaveTextContent("Confirmed 2 defects."));
  });

  it("keeps “Include drafts” while the list changes", async () => {
    mount();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Include drafts" }));
    fireEvent.click(screen.getByRole("button", { name: /^Confirmed/ }));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Include drafts" })).toBeChecked());
  });

  it("asks why before rejecting", async () => {
    const fetch = mount({ [DECIDE]: { changed: 1 } }).fetch;
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select DEF-003" }));
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    const confirm = screen.getByRole("button", { name: "Reject 1 defect" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: /Why/ }), { target: { value: "works as designed" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(sentBody(fetch, "POST", "/defects/decisions")).toEqual({ ids: ["DEF-003"], decision: "rejected", why: "works as designed" }));
  });

  it("shows evidence by its number, never by a file path", async () => {
    mount();
    const card = (await screen.findAllByRole("article"))[0];
    const shots = within(card).getAllByRole("img");
    expect(shots[0]).toHaveAttribute("src", "/api/v1/projects/demo/defects/DEF-001/evidence/0");
    expect(shots[0]).toHaveAccessibleName("Evidence 1: screenshot (officer)");
    expect(within(card).getByRole("link", { name: "Download evidence 2: trace (officer)" })).toHaveAttribute(
      "href", "/api/v1/projects/demo/defects/DEF-001/evidence/1");
  });

  it("says an evidence picture's file is missing instead of showing a broken image", async () => {
    mount();
    const card = (await screen.findAllByRole("article"))[0];
    fireEvent.error(within(card).getAllByRole("img")[0]);
    expect(within(card).getByText("The picture file is missing or could not be loaded")).toBeInTheDocument();
    expect(within(card).queryByRole("link", { name: /Evidence 1/ })).toBeNull();
  });

  it("downloads confirmed defects only unless drafts are included", async () => {
    mount();
    const jira = await screen.findByRole("link", { name: "Defects for Jira (CSV)" });
    expect(jira).toHaveAttribute("href", "/api/v1/projects/demo/defects/export.csv?drafts=0");
    fireEvent.click(screen.getByRole("checkbox", { name: "Include drafts" }));
    expect(screen.getByRole("link", { name: "Defects for Zoho (CSV)" })).toHaveAttribute("href", "/api/v1/projects/demo/defects/zoho.csv?drafts=1");
  });

  it("shows a hostile defect from the application as text, and a defect already sent to a tracker cannot be selected", async () => {
    const d = demo();
    d.defects.items[0] = { ...d.defects.items[0], title: "<img src=x onerror=alert(1)>", url: "javascript:alert(1)" };
    d.defects.items[1] = { ...d.defects.items[1], status: "exported", external_key: "QA-7" };
    renderPage(<Defects />, "/projects/demo/defects", "/projects/:slug/defects", { "GET /projects/demo/defects": d.defects });
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(screen.getByText("javascript:alert(1)").closest("a")).toBeNull();
    expect(screen.queryByRole("checkbox", { name: `Select ${d.defects.items[1].id}` })).toBeNull();
  });

  it("shows the application's addresses as text, not links", async () => {
    mount();
    expect((await screen.findAllByText("http://127.0.0.1:8810/api/users")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: /127\.0\.0\.1/ })).toBeNull();
  });

  it("a Viewer reads the defects and downloads, with no controls", async () => {
    mount({}, "viewer");
    expect(await screen.findAllByRole("article")).toHaveLength(19);
    expect(screen.queryByRole("checkbox", { name: /Select/ })).toBeNull();
    // The chips "Confirmed (0)" / "Rejected (0)" are filters, not decisions: only decision buttons must be absent.
    for (const name of ["Confirm", "Reject", "Back to draft"]) expect(screen.queryByRole("button", { name })).toBeNull();
    expect(screen.getByRole("link", { name: "Defects for Jira (CSV)" })).toBeInTheDocument();
  });
});
