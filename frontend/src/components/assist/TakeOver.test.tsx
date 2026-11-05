import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { cleanPending } from "../../lib/assist";
import { fail, sentBody, stubFetch } from "../../test-fetch";
import { renderPage } from "../../test-fixtures/gates";
import { pending, takeover, type RawWaiting } from "../../test-fixtures/assist";
import { TakeOver } from "./TakeOver";

const COMMANDS = "POST /projects/demo/assist/9/commands";
const SELECTED = "Type into the selected box";
const NEWS = { name: "Take-over news" };
const item = (raw: RawWaiting) => cleanPending(pending([raw])).items[0];
const bodies = (fetch: ReturnType<typeof renderPage>["fetch"]) => fetch.mock.calls
  .filter(([url, init]) => init?.method === "POST" && String(url).endsWith("/commands")).map(([, init]) => JSON.parse(String(init?.body)));
const rect = (left: number, top: number, width: number, height: number): DOMRect =>
  ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) });
const pause = (ms = 40) => new Promise((done) => setTimeout(done, ms));

function mount(raw: RawWaiting = takeover(), routes: Record<string, unknown> = {}) {
  return renderPage(<TakeOver slug="demo" item={item(raw)} onMinimise={vi.fn()} />, "/projects/demo", "/projects/:slug", {
    [COMMANDS]: { id: 1 }, "POST /projects/demo/assist/9/answer": { id: 9, status: "answered" }, ...routes,
  });
}

const press = (name: string) => fireEvent.click(screen.getByRole("button", { name }));
const pick = (name: string) => press(`Box on the screen: ${name}`);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("taking over the agent's browser", () => {
  it("fills the screen with the live screenshot at the browser's own size", () => {
    mount();
    expect(screen.getByRole("dialog", { name: "You have the explorer's browser (as citizen)" })).toHaveAttribute("aria-modal", "true");
    const shot = screen.getByRole("img", { name: /The explorer's screen/ });
    expect(shot).toHaveAttribute("src", "/api/v1/projects/demo/assist/9/shot?v=3");
    expect(shot).toHaveAttribute("width", "1280");
    expect(shot).toHaveAttribute("height", "800");
  });

  it("sends each button's own command", async () => {
    const { fetch } = mount();
    for (const name of ["Enter", "Tab", "Backspace", "Back", "Scroll down", "Scroll up"]) press(name);
    press("Button on the screen: Get OTP");
    fireEvent.change(screen.getByRole("textbox", { name: "Open an address on the portal" }), { target: { value: "/apply" } });
    press("Open");
    await waitFor(() => expect(bodies(fetch)).toEqual([
      { kind: "press", key: "Enter" }, { kind: "press", key: "Tab" }, { kind: "press", key: "Backspace" }, { kind: "back" },
      { kind: "scroll", dy: 400 }, { kind: "scroll", dy: -400 }, { kind: "click", x: 700, y: 400 }, { kind: "goto", path: "/apply" },
    ]));
  });

  it("types into a password box as a secret, in a password-style box", async () => {
    const { fetch } = mount();
    pick("Password");
    const field = screen.getByLabelText(SELECTED);
    expect(field).toHaveAttribute("type", "password");
    fireEvent.change(field, { target: { value: "Clerk@123" } });
    press("Type it");
    await waitFor(() => expect(bodies(fetch).at(-1)).toEqual({ kind: "type", text: "Clerk@123", secret: true, replace: false }));
    await waitFor(() => expect(field).toHaveValue(""));
  });

  it("on a production application, a red warning and a tick come before the first command", async () => {
    const { fetch } = mount(takeover({ production: true }));
    expect(screen.getByRole("dialog")).toHaveAccessibleDescription(/live production application/);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Enter" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I understand/ }));
    press("Enter");
    await waitFor(() => expect(bodies(fetch)).toEqual([{ kind: "press", key: "Enter" }]));
  });

  it("sends nothing on a production application before the tick, whatever reaches the form", async () => {
    const { fetch } = mount(takeover({ production: true }));
    const address = screen.getByRole("textbox", { name: "Open an address on the portal" });
    fireEvent.change(address, { target: { value: "/apply" } });
    fireEvent.submit(address.closest("form") as HTMLFormElement);
    const typed = screen.getByLabelText(SELECTED);
    fireEvent.change(typed, { target: { value: "abc" } });
    fireEvent.submit(typed.closest("form") as HTMLFormElement);
    await pause();
    expect(bodies(fetch)).toEqual([]);
  });

  it("reloads the screenshot only when a new one is there", () => {
    stubFetch({});
    const client = new QueryClient();
    const at = (shotV: number) => (
      <QueryClientProvider client={client}><MemoryRouter><TakeOver slug="demo" item={item(takeover({ shot_v: shotV }))} onMinimise={vi.fn()} /></MemoryRouter></QueryClientProvider>
    );
    const { rerender } = render(at(3));
    const src = screen.getByRole("img", { name: /The explorer's screen/ }).getAttribute("src");
    rerender(at(3));
    expect(screen.getByRole("img", { name: /The explorer's screen/ }).getAttribute("src")).toBe(src);
    rerender(at(4));
    expect(screen.getByRole("img", { name: /The explorer's screen/ })).toHaveAttribute("src", "/api/v1/projects/demo/assist/9/shot?v=4");
  });

  it("lists the last six actions as text", () => {
    mount();
    const done = screen.getByRole("list", { name: "What you did" });
    expect(done.querySelectorAll("li")).toHaveLength(6);
    expect(done).not.toHaveTextContent("Clicked at (1, 1)");
    expect(done).toHaveTextContent("Opened /apply");
  });

  it("hands back with Continue, or cancels", async () => {
    const { fetch } = mount(takeover({ headed: true }));
    expect(screen.getByText(/browser window is also open on this computer/)).toBeInTheDocument();
    press("Continue: I'm done");
    await waitFor(() => expect(sentBody(fetch, "POST", "/assist/9/answer")).toEqual({ done: true }));
    cleanup();
    const second = mount();
    press("Cancel");
    await waitFor(() => expect(sentBody(second.fetch, "POST", "/assist/9/answer")).toEqual({ skip: true }));
  });

  it("says so when the browser is no longer handed over", async () => {
    mount(takeover(), { [COMMANDS]: fail(409, "not_handed_over", "This browser is no longer handed over") });
    press("Enter");
    expect(await screen.findByRole("alert")).toHaveTextContent(/no longer handed over/);
  });
});

describe("what is typed", () => {
  it("is hidden unless the person asks to see it, and never for a password box", async () => {
    const { fetch } = mount();
    const field = screen.getByLabelText(SELECTED);
    expect(field).toHaveAttribute("type", "password");                    // nothing chosen yet: the cursor may be in a password box
    expect(field).toHaveAttribute("autocomplete", "new-password");
    expect(field).toHaveAttribute("spellcheck", "false");
    expect(field).toHaveAttribute("autocapitalize", "off");
    pick("Registered number");
    fireEvent.click(screen.getByRole("checkbox", { name: "Show what I type" }));
    expect(field).toHaveAttribute("type", "text");
    fireEvent.change(field, { target: { value: "9876543210" } });
    press("Type it");
    await waitFor(() => expect(bodies(fetch).at(-1)).toEqual({ kind: "type", text: "9876543210", secret: false, replace: false }));
    pick("Password");
    expect(field).toHaveAttribute("type", "password");
    expect(screen.getByRole("checkbox", { name: "Show what I type" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Show what I type" })).toBeDisabled();
  });

  it("is sent as a secret while it is hidden", async () => {
    const { fetch } = mount();
    pick("Registered number");
    fireEvent.change(screen.getByLabelText(SELECTED), { target: { value: "9876543210" } });
    press("Type it");
    await waitFor(() => expect(bodies(fetch).at(-1)).toEqual({ kind: "type", text: "9876543210", secret: true, replace: false }));
  });

  it("is sent exactly as typed, spaces and all", async () => {
    const { fetch } = mount();
    fireEvent.change(screen.getByLabelText(SELECTED), { target: { value: "  pa  ss " } });
    press("Type it");
    await waitFor(() => expect(bodies(fetch).at(-1)).toMatchObject({ kind: "type", text: "  pa  ss " }));
  });

  it("stays in the box when the command fails, and is cleared when it works", async () => {
    let works = false;
    const { fetch } = mount(takeover(), { [COMMANDS]: () => (works ? { id: 1 } : fail(409, "not_handed_over", "This browser is no longer handed over")) });
    const field = screen.getByLabelText(SELECTED);
    fireEvent.change(field, { target: { value: "keep me" } });
    press("Type it");
    await screen.findByRole("alert");
    expect(field).toHaveValue("keep me");
    const address = screen.getByRole("textbox", { name: "Open an address on the portal" });
    fireEvent.change(address, { target: { value: "/apply" } });
    press("Open");
    await waitFor(() => expect(bodies(fetch)).toHaveLength(2));
    await pause();
    expect(address).toHaveValue("/apply");
    works = true;
    press("Type it");
    await waitFor(() => expect(field).toHaveValue(""));
    press("Open");
    await waitFor(() => expect(address).toHaveValue(""));
  });

  it("is not kept in the request cache once it is sent", async () => {
    const { client, fetch } = mount();
    fireEvent.change(screen.getByLabelText(SELECTED), { target: { value: "Zq7-secret" } });
    press("Type it");
    await waitFor(() => expect(bodies(fetch).at(-1)).toMatchObject({ text: "Zq7-secret" }));
    await waitFor(() => expect(JSON.stringify(client.getMutationCache().getAll().map((m) => m.state.variables))).not.toContain("Zq7-secret"));
  });
});

describe("the box that is selected", () => {
  const forgets: [string, () => void][] = [
    ["Tab", () => press("Tab")],
    ["Enter", () => press("Enter")],
    ["an address", () => {
      fireEvent.change(screen.getByRole("textbox", { name: "Open an address on the portal" }), { target: { value: "/apply" } });
      press("Open");
    }],
    ["a click on the screen", () => {
      vi.spyOn(screen.getByRole("img", { name: /screen/ }), "getBoundingClientRect").mockReturnValue(rect(0, 0, 640, 400));
      fireEvent.click(screen.getByRole("button", { name: /Click on the screen/ }), { clientX: 10, clientY: 10, detail: 1 });
    }],
  ];

  it.each(forgets)("is forgotten after %s, and so is the wish to see what is typed", async (_, doIt) => {
    const { fetch } = mount();
    pick("Registered number");
    fireEvent.click(screen.getByRole("checkbox", { name: "Show what I type" }));
    expect(screen.getByText(/\(selected: Registered number\)/)).toBeInTheDocument();
    await screen.findByText("Sent: click at (600, 300)");                    // the click on the box is done; the screen is free again
    await waitFor(() => expect(screen.getByRole("button", { name: /Click on the screen/ })).toBeEnabled());
    const before = bodies(fetch).length;
    doIt();
    await waitFor(() => expect(bodies(fetch).length).toBeGreaterThan(before));
    expect(screen.queryByText(/\(selected:/)).toBeNull();
    expect(screen.getByLabelText(SELECTED)).toHaveAttribute("type", "password");
    expect(screen.getByRole("checkbox", { name: "Show what I type" })).not.toBeChecked();
  });

  it("stays selected after a key that does not move the cursor", async () => {
    const { fetch } = mount();
    pick("Registered number");
    press("Backspace");
    await waitFor(() => expect(bodies(fetch).at(-1)).toEqual({ kind: "press", key: "Backspace" }));
    expect(screen.getByText(/\(selected: Registered number\)/)).toBeInTheDocument();
  });
});

describe("commands, one at a time", () => {
  it("run in the order they were given, the next after the last has been answered", async () => {
    const view = mount();
    const releases: (() => void)[] = [];
    const started: string[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (!String(url).endsWith("/commands")) return view.fetch(url, init);
      started.push(JSON.parse(String(init?.body)).key);
      await new Promise<void>((release) => releases.push(release));
      return view.fetch(url, init);
    });
    press("Enter");
    press("Tab");
    press("Backspace");
    await waitFor(() => expect(started).toEqual(["Enter"]));
    await pause();
    expect(started).toEqual(["Enter"]);
    releases[0]();
    await waitFor(() => expect(started).toEqual(["Enter", "Tab"]));
    releases[1]();
    await waitFor(() => expect(started).toEqual(["Enter", "Tab", "Backspace"]));
    releases[2]();
    await waitFor(() => expect(bodies(view.fetch)).toHaveLength(3));
  });

  it("do not double when the screen is clicked twice, or while a command is on its way", async () => {
    const view = mount();
    const release: (() => void)[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (String(url).endsWith("/commands")) await new Promise<void>((done) => release.push(done));
      return view.fetch(url, init);
    });
    const shot = screen.getByRole("button", { name: /Click on the screen/ });
    vi.spyOn(screen.getByRole("img", { name: /screen/ }), "getBoundingClientRect").mockReturnValue(rect(0, 0, 640, 400));
    fireEvent.click(shot, { clientX: 320, clientY: 200, detail: 1 });
    fireEvent.click(shot, { clientX: 320, clientY: 200, detail: 2 });          // the second click of a double click
    await waitFor(() => expect(release).toHaveLength(1));
    expect(shot).toBeDisabled();
    fireEvent.click(shot, { clientX: 100, clientY: 100, detail: 1 });
    release[0]();
    await waitFor(() => expect(shot).toBeEnabled());
    await pause();
    expect(bodies(view.fetch)).toEqual([{ kind: "click", x: 640, y: 400 }]);
  });
});

describe("saying what happened", () => {
  it("says what was sent in words, and never the text typed", async () => {
    mount();
    press("Enter");
    expect(await screen.findByText("Sent: Enter")).toBeInTheDocument();
    expect(screen.getByRole("status", NEWS)).toHaveTextContent("Sent: Enter");
    pick("Password");
    fireEvent.change(screen.getByLabelText(SELECTED), { target: { value: "Clerk@123" } });
    press("Type it");
    await waitFor(() => expect(screen.getByRole("status", NEWS)).toHaveTextContent("Sent: typed 9 characters"));
    expect(document.body).not.toHaveTextContent("Clerk@123");
  });

  it("names a box that is filled, and a button or box with no words on it", () => {
    mount(takeover({
      fields: [{ label: "Registered number", type: "tel", x: 1, y: 2, filled: true }, { label: "", type: "", x: 3, y: 4, filled: false }],
      clickables: [{ text: "", x: 5, y: 6 }],
    }));
    expect(screen.getByRole("button", { name: "Box on the screen: Registered number (filled)" })).toHaveTextContent("Registered number ✓");
    expect(screen.getByRole("button", { name: "Box on the screen: (no text)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Button on the screen: (no text)" })).toBeInTheDocument();
  });

  it("describes the screenshot by the boxes and buttons beside it", () => {
    mount();
    const shot = screen.getByRole("button", { name: /Click on the screen/ });
    expect(shot).toHaveAccessibleDescription(/use the buttons/i);
    expect(shot).toHaveAccessibleDescription(/Get OTP/);
    expect(within(screen.getByRole("list", { name: "Boxes on the screen" })).getAllByRole("button")).toHaveLength(2);
  });
});
