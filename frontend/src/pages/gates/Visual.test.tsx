import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, renderHook, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { sentBody, stubFetch } from "../../test-fetch";
import { demo, renderPage } from "../../test-fixtures/gates";
import { visualView } from "../../test-fixtures/assist";
import { Visual, useVisualDecisions } from "./Visual";

const KEY = "citizen@citizen_apply";
const DECIDE = `POST /projects/demo/visual/${encodeURIComponent(KEY)}`;

function mount(extra: Record<string, unknown> = {}, role = "owner") {
  return renderPage(<Visual />, "/projects/demo/visual", "/projects/:slug/visual", {
    "GET /projects/demo/visual": visualView(), "GET /projects/demo/gates": demo().gates, ...extra,
  }, role);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Visual review page", () => {
  it("shows each changed screen's pictures by key, never by a file path, and its address as text", async () => {
    mount();
    const card = (await screen.findAllByRole("article"))[0];
    expect(within(card).getByRole("heading", { name: "/apply" })).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: "The approved baseline of /apply (citizen)" }))
      .toHaveAttribute("src", `/api/v1/projects/demo/visual/${encodeURIComponent(KEY)}/baseline`);
    expect(within(card).getByRole("img", { name: "Now: /apply (citizen)" })).toHaveAttribute("src", `/api/v1/projects/demo/visual/${encodeURIComponent(KEY)}/current`);
    expect(within(card).getByText("12.5% of the layout differs")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /\/apply/ })).toBeNull();
    const second = screen.getAllByRole("article")[1];
    expect(within(second).getByText("No difference picture")).toBeInTheDocument();
  });

  it("asks why before keeping a changed screen as its new baseline", async () => {
    const { fetch } = mount({ [DECIDE]: { key: KEY, status: "approved" } });
    const card = (await screen.findAllByRole("article"))[0];
    fireEvent.click(within(card).getByRole("button", { name: "Approve as the new baseline: /apply (citizen)" }));
    const confirm = within(card).getByRole("button", { name: "Keep the new look" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(card).getByRole("textbox", { name: /Why/ }), { target: { value: "the redesign shipped" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(sentBody(fetch, "POST", `/visual/${encodeURIComponent(KEY)}`)).toEqual({ decision: "approve", why: "the redesign shipped" }));
  });

  it("reports a change as a defect, a reason optional, and says which defect it became", async () => {
    mount({ [DECIDE]: { key: KEY, status: "reported", defect: "DEF-020" } });
    const card = (await screen.findAllByRole("article"))[0];
    fireEvent.click(within(card).getByRole("button", { name: "Report as a defect: /apply (citizen)" }));
    fireEvent.click(within(card).getByRole("button", { name: "Report it" }));
    await waitFor(() => expect(screen.getByRole("status", { name: "Updates" })).toHaveTextContent("Reported as DEF-020."));
  });

  it("approves every changed screen with one reason", async () => {
    const { fetch } = mount({ "POST /projects/demo/visual/approve-all": { approved: 2, skipped: 0 } });
    fireEvent.click(await screen.findByRole("button", { name: "Approve every changed screen" }));
    fireEvent.change(screen.getByRole("textbox", { name: /Why/ }), { target: { value: "new theme" } });
    fireEvent.click(screen.getByRole("button", { name: "Keep all 2 new looks" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/visual/approve-all")).toEqual({ why: "new theme" }));
  });

  it("says how many screens could not be kept when some were left out", async () => {
    mount({ "POST /projects/demo/visual/approve-all": { approved: 1, skipped: 1 } });
    fireEvent.click(await screen.findByRole("button", { name: "Approve every changed screen" }));
    fireEvent.change(screen.getByRole("textbox", { name: /Why/ }), { target: { value: "new theme" } });
    fireEvent.click(screen.getByRole("button", { name: "Keep all 2 new looks" }));
    const words = "Kept 1 new look. 1 screen could not be kept and still needs a decision.";
    await waitFor(() => expect(screen.getByRole("status", { name: "Updates" })).toHaveTextContent(words));
    expect(screen.getByText(words, { selector: ".notice" })).toBeInTheDocument();
  });

  it("keeps the tested site's address in its own direction inside the question about it", async () => {
    mount();
    const card = (await screen.findAllByRole("article"))[0];
    fireEvent.click(within(card).getByRole("button", { name: "Approve as the new baseline: /apply (citizen)" }));
    const dialog = within(card).getByRole("dialog", { name: "Keep the new look of /apply (citizen) as its baseline?" });
    expect(within(dialog).getByText("/apply (citizen)").tagName).toBe("BDI");
  });

  it("hands its cards one decide function, which stays the same while a decision runs", async () => {
    stubFetch({ [DECIDE]: { key: KEY, status: "approved" } });
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const done = vi.fn();
    const { result } = renderHook(() => useVisualDecisions("demo", done), {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    });
    const first = result.current.decide;
    act(() => result.current.decide(KEY, "approve", "because", "/apply"));
    await waitFor(() => expect(done).toHaveBeenCalled());
    await waitFor(() => expect(result.current.one.isPending).toBe(false));
    expect(result.current.decide).toBe(first);
  });

  it("says the picture file is missing or could not be loaded instead of a broken image", async () => {
    mount();
    const card = (await screen.findAllByRole("article"))[0];
    fireEvent.error(within(card).getByRole("img", { name: "Now: /apply (citizen)" }));
    expect(within(card).getByText("The picture file is missing or could not be loaded")).toBeInTheDocument();
  });

  it("a Viewer sees the screens with no controls", async () => {
    mount({}, "viewer");
    expect(await screen.findAllByRole("article")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /^(Approve as|Approve every|Report as)/ })).toBeNull();     // the chips are views
  });
});
