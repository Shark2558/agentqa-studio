import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { sentBody } from "../test-fetch";
import { demo, renderPage } from "../test-fixtures/gates";
import { Requirements } from "./Requirements";

const LIST = "GET /projects/demo/requirements";

function mount(routes: Record<string, unknown> = {}, role = "owner") {
  return renderPage(<Requirements />, "/projects/demo/requirements", "/projects/:slug/requirements", { [LIST]: demo().requirements, ...routes }, role);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Requirements page", () => {
  it("says how many there are and shows each one's disposition with its note", async () => {
    mount();
    expect(await screen.findByText(/35 requirements from 1 document/)).toBeInTheDocument();
    expect(screen.getAllByText("covered").length).toBeGreaterThan(0);
    expect(screen.getAllByText("19 test case(s)").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("offers only the four dispositions a person may set, and asks why", async () => {
    const fetch = mount({ "PATCH /projects/demo/requirements/FR-01": { ...demo().requirements.requirements[0], disposition: "manual" } }).fetch;
    const menu = await screen.findByRole("combobox", { name: "New disposition for FR-01" });
    expect(within(menu).getAllByRole("option").map((o) => o.getAttribute("value"))).toEqual(["", "out_of_scope", "not_testable", "manual", "clarify"]);
    const set = screen.getByRole("button", { name: "Set the disposition of FR-01" });
    expect(set).toBeDisabled();
    // Choosing in the menu (arrow keys fire a change on each step) must not open anything or move focus (WCAG 3.2.2)
    fireEvent.change(menu, { target: { value: "manual" } });
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(set);
    const confirm = screen.getByRole("button", { name: "Set FR-01 to “Tested by hand”" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: /Why/ }), { target: { value: "needs a real SMS" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(sentBody(fetch, "PATCH", "/requirements/FR-01")).toEqual({ disposition: "manual", why: "needs a real SMS" }));
  });

  it("loads the next 200 with Show more when there are more", async () => {
    let calls = 0;
    const page = demo().requirements;
    const more = { ...page, requirements: [{ ...page.requirements[0], id: "FR-99", seq: 99 }], total: 36 };
    const { fetch } = mount({ [LIST]: () => (calls++ === 0 ? { ...page, total: 36 } : more) });
    expect(await screen.findByText(/35 of 36 requirements/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(await screen.findByText("FR-99")).toBeInTheDocument();
    expect(String(fetch.mock.calls.at(-1)?.[0])).toContain("offset=35");
  });

  it("keeps an id written in a document as one path segment (BR/01)", async () => {
    const page = demo().requirements;
    const odd = { ...page, requirements: [{ ...page.requirements[0], id: "BR/01" }] };
    const fetch = mount({ [LIST]: odd, "PATCH /projects/demo/requirements/BR%2F01": { ...odd.requirements[0], disposition: "clarify" } }).fetch;
    fireEvent.change(await screen.findByRole("combobox", { name: "New disposition for BR/01" }), { target: { value: "clarify" } });
    fireEvent.click(screen.getByRole("button", { name: "Set the disposition of BR/01" }));
    fireEvent.change(screen.getByRole("textbox", { name: /Why/ }), { target: { value: "the SRS gives no numbers" } });
    fireEvent.click(screen.getByRole("button", { name: "Set BR/01 to “To clarify”" }));
    await waitFor(() => expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/requirements/BR%2F01"))).toBe(true));
  });

  it("links the traceability matrix download", async () => {
    mount();
    expect(await screen.findByRole("link", { name: /traceability matrix/ })).toHaveAttribute("href", "/api/v1/projects/demo/requirements/rtm.xlsx");
  });

  it("a Viewer sees the dispositions without the menu", async () => {
    mount({}, "viewer");
    expect(await screen.findByText(/35 requirements/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("combobox")).toBeNull());
  });
});
