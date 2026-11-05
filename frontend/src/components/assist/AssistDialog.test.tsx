import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { cleanPending } from "../../lib/assist";
import { fail, sentBody } from "../../test-fetch";
import { renderPage } from "../../test-fixtures/gates";
import { pending, waiting, type RawWaiting } from "../../test-fixtures/assist";
import { AssistDialog } from "./AssistDialog";

const ANSWER = "POST /projects/demo/assist/7/answer";
const box = (left: number, top: number, width: number, height: number): DOMRect =>
  ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) });

function mount(raw: RawWaiting = waiting(), routes: Record<string, unknown> = {}) {
  const [item] = cleanPending(pending([raw])).items;
  const onMinimise = vi.fn();
  const view = renderPage(<AssistDialog slug="demo" item={item} onMinimise={onMinimise} />, "/projects/demo", "/projects/:slug",
                          { [ANSWER]: { id: 7, status: "answered" }, ...routes });
  return { ...view, onMinimise };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the help box's question", () => {
  it("opens as a dialog over the page, with the question as text", () => {
    mount(waiting({ question: "<b>Which</b> button?" }));
    const dialog = screen.getByRole("dialog", { name: "<b>Which</b> button?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("The explorer (as citizen)")).toBeInTheDocument();
    expect(screen.getByText("http://127.0.0.1:8800/").closest("a")).toBeNull();
  });

  it("answers with a choice", async () => {
    const { fetch } = mount();
    fireEvent.click(screen.getByRole("button", { name: "Department Login" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/assist/7/answer")).toEqual({ option: 1 }));
  });

  it("answers with a button on the screen: its place and its words", async () => {
    const { fetch } = mount();
    fireEvent.click(screen.getByRole("button", { name: "On the screen: Citizen Login" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/assist/7/answer")).toEqual({ x: 640, y: 212, text: "Citizen Login" }));
  });

  it("scales a click on the screenshot itself (not on its framed button) to the agent's browser", async () => {
    const { fetch } = mount();
    const shot = screen.getByRole("button", { name: /Click on the screen/ });
    vi.spyOn(shot, "getBoundingClientRect").mockReturnValue(box(10, 20, 642, 402));      // the button, with its 1 px frame
    vi.spyOn(screen.getByRole("img", { name: /screen/ }), "getBoundingClientRect").mockReturnValue(box(11, 21, 640, 400));
    fireEvent.click(shot, { clientX: 600, clientY: 400, detail: 1 });
    await waitFor(() => expect(sentBody(fetch, "POST", "/assist/7/answer")).toEqual({ x: 1178, y: 758 }));
  });

  it("keeps a click on the picture's last pixel on the agent's screen", async () => {
    const { fetch } = mount();
    const shot = screen.getByRole("button", { name: /Click on the screen/ });
    vi.spyOn(screen.getByRole("img", { name: /screen/ }), "getBoundingClientRect").mockReturnValue(box(0, 0, 640, 400));
    fireEvent.click(shot, { clientX: 640, clientY: 400, detail: 1 });
    await waitFor(() => expect(sentBody(fetch, "POST", "/assist/7/answer")).toEqual({ x: 1279, y: 799 }));
  });

  it("answers with the first click of a double click only", async () => {
    const { fetch } = mount();
    const shot = screen.getByRole("button", { name: /Click on the screen/ });
    vi.spyOn(screen.getByRole("img", { name: /screen/ }), "getBoundingClientRect").mockReturnValue(box(0, 0, 640, 400));
    fireEvent.click(shot, { clientX: 320, clientY: 200, detail: 2 });
    await new Promise((done) => setTimeout(done, 40));
    expect(fetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    fireEvent.click(shot, { clientX: 320, clientY: 200, detail: 1 });
    await waitFor(() => expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1));
  });

  it("tells a keyboard or screen-reader user to use the buttons, and describes the picture by them", () => {
    mount();
    const shot = screen.getByRole("button", { name: /Click on the screen/ });
    expect(shot).toHaveAccessibleDescription(/use the buttons below/i);
    expect(shot).toHaveAccessibleDescription(/Citizen Login/);
    const help = screen.getByRole("status", { name: "Screenshot help" });
    expect(help).toBeEmptyDOMElement();
    fireEvent.click(shot, { detail: 0 });
    expect(help).toHaveTextContent(/cannot point with the keyboard.*use the buttons below/i);
  });

  it("does not close when a press in the answer box is released on the backdrop (a drag)", () => {
    const { onMinimise } = mount();
    const backdrop = screen.getByRole("dialog");
    fireEvent.mouseDown(screen.getByRole("textbox", { name: "Your answer" }));
    fireEvent.mouseUp(backdrop);
    fireEvent.click(backdrop);
    expect(onMinimise).not.toHaveBeenCalled();
    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);
    expect(onMinimise).toHaveBeenCalledTimes(1);
  });

  it("asks for a one-time code with the number keypad and the code's autocomplete", async () => {
    const { fetch } = mount(waiting({ kind: "otp", options: [], clickables: [], secret: true, question: "Enter the OTP" }));
    const box = screen.getByRole("textbox", { name: "Your answer" });
    expect(box).toHaveAttribute("inputmode", "numeric");
    expect(box).toHaveAttribute("autocomplete", "one-time-code");
    fireEvent.change(box, { target: { value: "482913" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/assist/7/answer")).toEqual({ text: "482913" }));
  });

  it("answers a check of an expected result with one of its choices, or yes", async () => {
    const { fetch } = mount(waiting({ kind: "confirm", question: "Is the certificate shown?", options: ["Yes, as expected", "No: report it"], clickables: [] }));
    fireEvent.click(screen.getByRole("button", { name: "No: report it" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/assist/7/answer")).toEqual({ option: 1 }));
    expect(screen.queryByRole("button", { name: "Yes" })).toBeNull();           // its own choices say it; Yes and No beside them confuse
    cleanup();
    const plain = mount(waiting({ kind: "confirm", question: "Is the certificate shown?", options: [], clickables: [] }));
    fireEvent.click(screen.getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(sentBody(plain.fetch, "POST", "/assist/7/answer")).toEqual({ ok: true }));
    expect(screen.getByRole("button", { name: "No" })).toBeInTheDocument();
  });

  it("sends a typed answer exactly as typed, spaces and all", async () => {
    const { fetch } = mount(waiting({ kind: "otp", options: [], clickables: [], secret: true, question: "Enter the code" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Your answer" }), { target: { value: "  12 34  " } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/assist/7/answer")).toEqual({ text: "  12 34  " }));
  });

  it("keeps a typed secret out of reach of the browser: no suggestions, no spell check, no capital", () => {
    mount(waiting({ kind: "ask", options: [], clickables: [], secret: true, question: "What is the password?" }));
    const field = screen.getByLabelText("Your answer");
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("autocomplete", "new-password");
    expect(field).toHaveAttribute("spellcheck", "false");
    expect(field).toHaveAttribute("autocapitalize", "off");
  });

  it("does not keep what was typed in the request cache once it is sent", async () => {
    const { client, fetch } = mount(waiting({ kind: "otp", options: [], clickables: [], secret: true, question: "Enter the code" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Your answer" }), { target: { value: "482913" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/assist/7/answer")).toEqual({ text: "482913" }));
    await waitFor(() => expect(JSON.stringify(client.getMutationCache().getAll().map((m) => m.state.variables))).not.toContain("482913"));
  });

  it("gives a button with no words on it a name", () => {
    mount(waiting({ clickables: [{ text: "", x: 5, y: 6 }, { text: "Help", x: 40, y: 20 }], options: ["", "Department Login"] }));
    expect(screen.getByRole("button", { name: "On the screen: (no text)" })).toHaveTextContent("(no text)");
    expect(screen.getAllByRole("button", { name: "(no text)" })).toHaveLength(1);
  });

  it("lets the person take over, or skip", async () => {
    const { fetch } = mount();
    fireEvent.click(screen.getByRole("button", { name: "Let me take over" }));
    await waitFor(() => expect(sentBody(fetch, "POST", "/assist/7/answer")).toEqual({ takeover: true }));
    cleanup();
    const second = mount();
    fireEvent.click(screen.getByRole("button", { name: "I can't help: skip it" }));
    await waitFor(() => expect(sentBody(second.fetch, "POST", "/assist/7/answer")).toEqual({ skip: true }));
  });

  it("Escape only minimises it: it never skips the question", () => {
    const { fetch, onMinimise } = mount();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onMinimise).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("says plainly when someone else answered first", async () => {
    mount(waiting(), { [ANSWER]: fail(409, "answered", "This question was already answered or is out of time") });
    fireEvent.click(screen.getByRole("button", { name: "Citizen Login" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already answered/);
  });
});
