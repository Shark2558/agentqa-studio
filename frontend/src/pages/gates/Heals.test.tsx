import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, renderHook, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { sentBody, stubFetch } from "../../test-fetch";
import { demo, renderPage } from "../../test-fixtures/gates";
import { healsView } from "../../test-fixtures/assist";
import { Heals, useHealDecision } from "./Heals";

function mount(extra: Record<string, unknown> = {}, role = "owner") {
  return renderPage(<Heals />, "/projects/demo/heals", "/projects/:slug/heals", {
    "GET /projects/demo/heals": healsView(), "GET /projects/demo/gates": demo().gates, ...extra,
  }, role);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Heals page", () => {
  it("shows each proposed fix as before → after, the tested site's words as text", async () => {
    mount();
    const [locator, workflow, manual] = await screen.findAllByRole("article");
    expect(locator).toHaveTextContent("mobile (Mobile)");
    expect(locator).toHaveTextContent("mobile_no (Mobile number)");
    expect(workflow).toHaveTextContent("text=Verify {app_id}");
    expect(workflow).toHaveTextContent("text=Mark verified {app_id}");
    expect(within(manual).getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(within(manual).getByText(/check this test by hand/)).toBeInTheDocument();
    expect(within(manual).queryByRole("button")).toBeNull();
  });

  it("approves a fix without a reason and shows what the engine did", async () => {
    const { fetch } = mount({ "POST /projects/demo/heals/2": { id: 2, status: "approved", note: "project.yaml updated" } });
    const workflow = (await screen.findAllByRole("article"))[1];
    const approve = within(workflow).getByRole("button", { name: "Approve the fix 2" });
    expect(approve).toHaveTextContent(/^Approve the fix$/);                       // the name begins with the words on the button (2.5.3)
    fireEvent.click(approve);
    await waitFor(() => expect(sentBody(fetch, "POST", "/heals/2")).toEqual({ decision: "approve", why: "" }));
    await waitFor(() => expect(screen.getByRole("status", { name: "Updates" })).toHaveTextContent("Fix 2 approved: project.yaml updated."));
  });

  it("asks why before rejecting", async () => {
    const { fetch } = mount({ "POST /projects/demo/heals/3": { id: 3, status: "rejected", note: "" } });
    const locator = (await screen.findAllByRole("article"))[0];
    fireEvent.click(within(locator).getByRole("button", { name: "Reject fix 3" }));
    const confirm = within(locator).getByRole("button", { name: "Reject the fix" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(locator).getByRole("textbox", { name: /Why/ }), { target: { value: "the old field comes back" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(sentBody(fetch, "POST", "/heals/3")).toEqual({ decision: "reject", why: "the old field comes back" }));
  });

  it("warns when the engine could not change project.yaml", async () => {
    mount({ "POST /projects/demo/heals/2": { id: 2, status: "approved", note: "Could not find 'x' in workflow WF-01 in project.yaml: change it by hand" } });
    fireEvent.click(within((await screen.findAllByRole("article"))[1]).getByRole("button", { name: "Approve the fix 2" }));
    expect(await screen.findByText(/change it by hand/)).toBeInTheDocument();
  });

  it("hands its cards one decide function, which stays the same while a decision runs", async () => {
    stubFetch({ "POST /projects/demo/heals/2": { id: 2, status: "approved", note: "" } });
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const done = vi.fn();
    const { result } = renderHook(() => useHealDecision("demo", done), {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    });
    const first = result.current.decide;
    act(() => result.current.decide(2, "approve", ""));
    await waitFor(() => expect(done).toHaveBeenCalled());
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.decide).toBe(first);
  });

  it("a Viewer sees the fixes with no controls", async () => {
    mount({}, "viewer");
    expect(await screen.findAllByRole("article")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /^(Approve the|Reject) fix/ })).toBeNull();      // the chips are views
  });
});
