import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { fail } from "../../test-fetch";
import { renderPage } from "../../test-fixtures/gates";
import { NOT_PAUSED, PAUSED } from "../../test-fixtures/assist";
import { PauseButton } from "./PauseButton";

const posted = (fetch: ReturnType<typeof renderPage>["fetch"], path: string) =>
  fetch.mock.calls.some(([url, init]) => init?.method === "POST" && String(url).endsWith(path));

function mount(paused = NOT_PAUSED, running = true, routes: Record<string, unknown> = {}) {
  return renderPage(<PauseButton slug="demo" paused={paused} running={running} />, "/projects/demo", "/projects/:slug", {
    "POST /projects/demo/pause": PAUSED, "POST /projects/demo/resume": { ...NOT_PAUSED, handed_back: 0 }, ...routes,
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Pause and take over", () => {
  it("pauses every agent and says what that does", async () => {
    const { fetch } = mount();
    expect(screen.getByText(/Agents with a browser stop at their next step and hand it to you; the Writer, Designer, Triage and Reporter carry on/))
      .toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pause and take over" }));
    await waitFor(() => expect(posted(fetch, "/pause")).toBe(true));
  });

  it("while paused, resumes them all", async () => {
    const { fetch } = mount(PAUSED);
    fireEvent.click(screen.getByRole("button", { name: "Paused: resume all" }));
    await waitFor(() => expect(posted(fetch, "/resume")).toBe(true));
  });

  it("says in words that the agents are paused, and that they carry on again", async () => {
    mount();
    const news = screen.getByRole("status", { name: "Pause news" });
    expect(news).toBeEmptyDOMElement();
    fireEvent.click(screen.getByRole("button", { name: "Pause and take over" }));
    await waitFor(() => expect(news).toHaveTextContent(/^Paused: agents with a browser stop at their next step/));
    cleanup();
    mount(PAUSED);
    fireEvent.click(screen.getByRole("button", { name: "Paused: resume all" }));
    await waitFor(() => expect(screen.getByRole("status", { name: "Pause news" })).toHaveTextContent(/^Resumed: the agents carry on/));
  });

  it("keeps the focus on the button and ignores a second press while it works (it is marked, not disabled)", async () => {
    const view = mount();
    let release = () => {};
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (String(url).endsWith("/pause")) await new Promise<void>((done) => { release = done; });
      return view.fetch(url, init);
    });
    const button = screen.getByRole("button", { name: "Pause and take over" });
    button.focus();
    fireEvent.click(button);
    await waitFor(() => expect(button).toHaveAttribute("aria-disabled", "true"));
    expect(button).not.toBeDisabled();
    expect(button).toHaveFocus();
    fireEvent.click(button);
    release();
    await waitFor(() => expect(screen.getByRole("status", { name: "Pause news" })).toHaveTextContent(/^Paused: /));
    expect(view.fetch.mock.calls.filter(([url, init]) => init?.method === "POST" && String(url).endsWith("/pause"))).toHaveLength(1);
    expect(button).toHaveFocus();
  });

  it("is not offered when nothing runs and nothing is paused", () => {
    mount(NOT_PAUSED, false);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says plainly when there is nothing to pause", async () => {
    mount(NOT_PAUSED, true, { "POST /projects/demo/pause": fail(409, "not_running", "Nothing is running") });
    fireEvent.click(screen.getByRole("button", { name: "Pause and take over" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing is running, so there is nothing to pause.");
  });
});
