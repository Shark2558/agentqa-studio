import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { fail } from "../../test-fetch";
import { renderPage } from "../../test-fixtures/gates";
import { NOT_PAUSED, PAUSED, pending, takeover, waiting, watched } from "../../test-fixtures/assist";
import { forgetAnnounced } from "./dockHooks";
import { NeedsYouDock } from "./NeedsYouDock";

const ASSIST = "GET /projects/demo/assist";
const ANSWER = "POST /projects/demo/assist/7/answer";
const calls = (fetch: ReturnType<typeof renderPage>["fetch"], path: string) =>
  fetch.mock.calls.filter(([url]) => String(url).split("?")[0].endsWith(path)).length;
const NEWS = { name: "Help box news" };
const realFocus = HTMLElement.prototype.focus;

function mount(routes: Record<string, unknown> = {}, role = "owner", element: ReactElement = <NeedsYouDock slug="demo" />) {
  return renderPage(element, "/projects/demo", "/projects/:slug", {
    [ASSIST]: pending(), "GET /projects/demo/gates": { running: true, paused: false }, ...routes,
  }, role);
}

/** As in the app: the page lives in `#root` (which the dialog closes to the keyboard), the dialog in `document.body`. */
function mountInRoot(routes: Record<string, unknown> = {}, element: ReactElement = <NeedsYouDock slug="demo" />) {
  const root = document.body.appendChild(document.createElement("div"));
  root.id = "root";
  const view = mount(routes, "owner", element);
  root.append(view.container);
  return { ...view, root };
}

afterEach(() => {
  cleanup();
  document.getElementById("root")?.remove();
  vi.restoreAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(document, "visibilityState");
  document.documentElement.style.removeProperty("--dock-h");
  forgetAnnounced();
  document.title = "AgentQA Studio";
});

describe("AgentQA needs you (the dock)", () => {
  it("shows who waits and what they ask, as text, without taking the focus", async () => {
    const before = document.body.appendChild(document.createElement("button"));
    before.focus();
    mount({ [ASSIST]: pending([waiting({ question: "<img src=x onerror=alert(1)>" })]) });
    const dock = await screen.findByRole("complementary", { name: "AgentQA needs you" });
    expect(dock).toHaveTextContent("The explorer (as citizen)");
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(dock.querySelector("img")).toBeNull();
    expect(before).toHaveFocus();
    before.remove();
  });

  it("changes the tab's title while an agent waits, and puts it back after", async () => {
    document.title = "AgentQA Studio";
    const { fetch } = mount();
    await screen.findByRole("complementary", { name: "AgentQA needs you" });
    expect(document.title).toBe("(!) AgentQA needs you");
    fetch.mockClear();
    cleanup();
    expect(document.title).toBe("AgentQA Studio");
  });

  it("announces a new question once", async () => {
    mount();
    await waitFor(() => expect(screen.getByRole("status", NEWS)).toHaveTextContent(
      "The explorer (as citizen) needs you: Which button logs me in as a citizen?"));
  });

  it("asks again every 2 seconds while the tab is seen", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { fetch } = mount();
    await screen.findByRole("complementary", { name: "AgentQA needs you" });
    const first = calls(fetch, "/assist");
    await act(() => vi.advanceTimersByTimeAsync(2_100));
    expect(calls(fetch, "/assist")).toBe(first + 1);
  });

  it("opens the question, or the take-over, only when asked", async () => {
    mount({ [ASSIST]: pending([takeover()]) });
    fireEvent.click(await screen.findByRole("button", { name: "Take over" }));
    expect(await screen.findByRole("dialog", { name: /You have the explorer's browser/ })).toBeInTheDocument();
  });

  it("asks for browser notifications only when the button is pressed", async () => {
    const requestPermission = vi.fn(async () => "granted");
    vi.stubGlobal("Notification", Object.assign(vi.fn(), { permission: "default", requestPermission }));
    mount();
    await screen.findByRole("complementary", { name: "AgentQA needs you" });
    expect(requestPermission).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Tell me with a notification" }));
    await waitFor(() => expect(requestPermission).toHaveBeenCalledTimes(1));
  });

  it("a Viewer reads that AgentQA waits for the owner or a tester, with no controls and no screen", async () => {
    mount({ [ASSIST]: pending([watched()]) }, "viewer");
    const dock = await screen.findByRole("complementary", { name: "AgentQA needs you" });
    expect(dock).toHaveTextContent("AgentQA is waiting for the owner or a tester");
    expect(screen.queryByRole("button")).toBeNull();
    expect(dock.querySelector("img")).toBeNull();
  });

  it("stays out of sight when nothing waits, and offers Resume while the agents are paused", async () => {
    const { fetch } = mount({ [ASSIST]: pending([], NOT_PAUSED), "GET /projects/demo/gates": { running: false, paused: false } });
    await waitFor(() => expect(calls(fetch, "/assist")).toBeGreaterThan(0));
    expect(screen.queryByRole("complementary", { name: "AgentQA needs you" })).toBeNull();
    cleanup();
    mount({ [ASSIST]: pending([], PAUSED) });
    expect(await screen.findByRole("button", { name: "Paused: resume all" })).toBeInTheDocument();
  });
});

describe("notifications", () => {
  it("a browser that refuses to build one (Android Chrome: Illegal constructor) neither blanks the app nor hides the news", async () => {
    const refuse = vi.fn(function Refuse() {
      throw new TypeError("Illegal constructor");
    });
    vi.stubGlobal("Notification", Object.assign(refuse, { permission: "granted", requestPermission: vi.fn() }));
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    mount();
    expect(await screen.findByRole("complementary", { name: "AgentQA needs you" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("status", NEWS)).toHaveTextContent("needs you: Which button"));
    expect(refuse).toHaveBeenCalled();
  });

  it("after Allow or Block the focus goes to the dock's title, not into thin air", async () => {
    const requestPermission = vi.fn(async () => "granted");
    vi.stubGlobal("Notification", Object.assign(vi.fn(), { permission: "default", requestPermission }));
    mount();
    const ask = await screen.findByRole("button", { name: "Tell me with a notification" });
    ask.focus();
    fireEvent.click(ask);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Tell me with a notification" })).toBeNull());
    expect(screen.getByText("AgentQA needs you", { selector: "p" })).toHaveFocus();
  });
});

describe("what is said, and to whom", () => {
  it("says every new question, not only the first of them", async () => {
    mount({ [ASSIST]: pending([waiting(), waiting({ id: 8, question: "Is the second one here?" })]) });
    await waitFor(() => expect(screen.getByRole("status", NEWS)).toHaveTextContent("Which button logs me in as a citizen?"));
    expect(screen.getByRole("status", NEWS)).toHaveTextContent("Is the second one here?");
  });

  it("says a question that comes while the dialog is open, from outside the page the dialog closes to the keyboard", async () => {
    let list = pending([waiting()]);
    const { root, client } = mountInRoot({ [ASSIST]: () => list });
    fireEvent.click(await screen.findByRole("button", { name: "Open" }));
    await screen.findByRole("dialog");
    expect(root).toHaveAttribute("inert");
    list = pending([waiting(), waiting({ id: 8, question: "A second question arrived?" })]);
    await act(() => client.invalidateQueries({ queryKey: ["assist", "demo"] }));
    const region = screen.getByRole("status", NEWS);
    await waitFor(() => expect(region).toHaveTextContent("A second question arrived?"));
    expect(root.contains(region)).toBe(false);
  });

  it("does not say a question again when the person comes back to the project", async () => {
    mount();
    await waitFor(() => expect(screen.getByRole("status", NEWS)).toHaveTextContent("needs you: Which button"));
    cleanup();
    mount();
    await screen.findByRole("complementary", { name: "AgentQA needs you" });
    expect(screen.getByRole("status", NEWS)).toHaveTextContent("");
  });

  it("leaves the Pause button to the Live View's own header", async () => {
    renderPage(<NeedsYouDock slug="demo" />, "/projects/demo/live", "/projects/:slug/live", {
      [ASSIST]: pending(), "GET /projects/demo/gates": { running: true, paused: false },
    });
    await screen.findByRole("complementary", { name: "AgentQA needs you" });
    expect(screen.queryByRole("button", { name: "Pause and take over" })).toBeNull();
    cleanup();
    mount();
    expect(await screen.findByRole("button", { name: "Pause and take over" })).toBeInTheDocument();
  });
});

describe("the dialog and where the focus goes", () => {
  it("forgets the open question when the dock goes away, so coming back does not pop it open", async () => {
    const first = mount();
    fireEvent.click(await screen.findByRole("button", { name: "Open" }));
    await screen.findByRole("dialog");
    first.unmount();
    mount();
    await screen.findByRole("complementary", { name: "AgentQA needs you" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("gives the focus back to the button that opened it only once the page is open to the keyboard again", async () => {
    const { root } = mountInRoot();
    const open = await screen.findByRole("button", { name: "Open" });
    open.focus();
    const seen: { el: Element; inert: boolean }[] = [];
    vi.spyOn(HTMLElement.prototype, "focus").mockImplementation(function focusAndNote(this: HTMLElement) {
      seen.push({ el: this, inert: root.hasAttribute("inert") });
      realFocus.call(this);
    });
    fireEvent.click(open);
    fireEvent.click(await screen.findByRole("button", { name: "Minimise" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(root).not.toHaveAttribute("inert");
    const back = seen.filter((s) => s.el === open).at(-1);
    expect(back?.inert).toBe(false);
    expect(open).toHaveFocus();
  });

  it("after an answer, the focus goes to the next question's button", async () => {
    let list = pending([waiting(), waiting({ id: 8, question: "And this one?" })]);
    mountInRoot({ [ASSIST]: () => list, [ANSWER]: () => { list = pending([waiting({ id: 8, question: "And this one?" })]); return { id: 7, status: "answered" }; } });
    const open = await screen.findByRole("button", { name: "Open" });
    open.focus();
    fireEvent.click(open);
    fireEvent.click(await screen.findByRole("button", { name: "Citizen Login" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await screen.findByText("And this one?");
    expect(screen.getByRole("button", { name: "Open" })).toHaveFocus();
  });

  it("after the last answer, the focus goes to the page's heading, not to nothing", async () => {
    let list = pending([waiting()]);
    mountInRoot({ [ASSIST]: () => list, [ANSWER]: () => { list = pending([]); return { id: 7, status: "answered" }; } },
                <><h1>The project</h1><NeedsYouDock slug="demo" /></>);
    const open = await screen.findByRole("button", { name: "Open" });
    open.focus();
    fireEvent.click(open);
    fireEvent.click(await screen.findByRole("button", { name: "Citizen Login" }));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "AgentQA needs you" })).toBeNull());
    expect(screen.getByRole("heading", { name: "The project" })).toHaveFocus();
  });

  it("a failed poll does not close the open question or lose what was typed", async () => {
    let down = false;
    const { client } = mount({ [ASSIST]: () => (down ? fail(503, "unavailable", "The help box could not be read") : pending()) });
    fireEvent.click(await screen.findByRole("button", { name: "Open" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "Your answer" }), { target: { value: "half an answ" } });
    down = true;
    await act(() => client.invalidateQueries({ queryKey: ["assist", "demo"] }));
    await waitFor(() => expect(client.getQueryState(["assist", "demo"])?.status).toBe("error"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Your answer" })).toHaveValue("half an answ");
    down = false;
    await act(() => client.invalidateQueries({ queryKey: ["assist", "demo"] }));
    await waitFor(() => expect(client.getQueryState(["assist", "demo"])?.status).toBe("success"));
    expect(screen.getByRole("textbox", { name: "Your answer" })).toHaveValue("half an answ");
  });

  it("a successful poll without the question means it was answered elsewhere: the dialog closes", async () => {
    let list = pending();
    const { client } = mount({ [ASSIST]: () => list });
    fireEvent.click(await screen.findByRole("button", { name: "Open" }));
    await screen.findByRole("dialog");
    list = pending([]);
    await act(() => client.invalidateQueries({ queryKey: ["assist", "demo"] }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("the page stays clear of the dock", () => {
  it("puts the dock's height where the page's padding can read it, and takes it away with the dock", async () => {
    const watchers: (() => void)[] = [];
    vi.stubGlobal("ResizeObserver", class {
      constructor(cb: () => void) { watchers.push(cb); }
      observe() { /* the test calls the callback itself */ }
      unobserve() { /* nothing to undo */ }
      disconnect() { /* nothing to undo */ }
    });
    let height = 180;
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(() => ({ height, width: 380, top: 0, left: 0, right: 380, bottom: height, x: 0, y: 0, toJSON: () => ({}) }));
    mount();
    await screen.findByRole("complementary", { name: "AgentQA needs you" });
    const read = () => document.documentElement.style.getPropertyValue("--dock-h");
    expect(read()).toBe("180px");
    height = 241;
    act(() => watchers.forEach((w) => w()));
    expect(read()).toBe("241px");
    cleanup();
    expect(read()).toBe("");
  });
});
