import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { answer, cleanPending, command, commandWords, movesFocus, pollMs, portalPath, scalePoint, takes, whoWaits } from "./assist";
import { pending, takeover, waiting, watched } from "../test-fixtures/assist";

describe("the pending list as it arrives", () => {
  it("caps every part that comes from the tested site", () => {
    const raw = waiting({
      question: "Q".repeat(900), hint: "h".repeat(2000), options: Array(30).fill("o".repeat(300)),
      clickables: [...Array(60).fill({ text: "c".repeat(300), x: 1, y: 2 }), { text: "no place", x: null }, "junk"],
      log: Array(20).fill("l".repeat(300)), url: `http://x/${"a".repeat(3000)}`,
    });
    const [w] = cleanPending(pending([raw])).items;
    expect(w.question).toHaveLength(500);
    expect(w.hint).toHaveLength(1000);
    expect(w.options).toHaveLength(20);
    expect(new Set(w.options.map((o) => o.length))).toEqual(new Set([200]));
    expect(w.clickables).toHaveLength(40);
    expect(w.clickables[0]).toEqual({ text: "c".repeat(200), x: 1, y: 2 });
    expect(w.log).toHaveLength(12);
    expect(w.url).toHaveLength(2000);
    expect(w.full).toBe(true);
  });

  it("keeps a Viewer's item to who is waiting, and drops what is not an item", () => {
    const view = cleanPending({ items: [watched(), { id: "x" }, null, "junk"], paused: { on: true, at: "t", by: "b" } });
    expect(view.items).toHaveLength(1);
    expect(view.items[0]).toMatchObject({ id: 7, agent: "explorer", role: "citizen", full: false, hasShot: false, options: [] });
    expect(view.paused).toEqual({ on: true, at: "t", by: "b" });
    expect(cleanPending(null)).toEqual({ items: [], paused: { on: false, at: null, by: null } });
  });

  it("says who waits in plain words", () => {
    const [w] = cleanPending(pending([takeover()])).items;
    expect(whoWaits(w)).toBe("The explorer (as citizen)");
    expect(whoWaits({ ...w, role: null, agent: "" })).toBe("An agent");
  });

  it("strips the characters that turn text around, so the tested site cannot spoof what is shown", () => {
    const bidi = "‮‪‬⁦⁩‎‏؜";
    const [w] = cleanPending(pending([waiting({ question: `Click ${bidi}Pay`, options: [`${bidi}Yes`], role: `ci${bidi}tizen` })])).items;
    expect(w.question).toBe("Click Pay");
    expect(w.options).toEqual(["Yes"]);
    expect(w.role).toBe("citizen");
  });

  it("keeps a screenshot version as large as the server counts, not only up to ten thousand", () => {
    const [w] = cleanPending(pending([waiting({ shot_v: 123_456 })])).items;
    expect(w.shotV).toBe(123_456);
    expect(cleanPending(pending([waiting({ shot_v: 2 ** 31 })])).items[0].shotV).toBe(0);
  });
});

describe("how often to ask", () => {
  it("every 2 s while the tab is seen, every second during a take-over, every 10 s while hidden", () => {
    expect(pollMs({ visible: true, takingOver: false, error: null })).toBe(2_000);
    expect(pollMs({ visible: true, takingOver: true, error: null })).toBe(1_000);
    expect(pollMs({ visible: false, takingOver: true, error: null })).toBe(10_000);
  });

  it("stops only when signed out or not allowed, and slows down after any other blip (a 404 may pass)", () => {
    expect(pollMs({ visible: true, takingOver: false, error: new ApiError(401, "unauthenticated", "x") })).toBe(false);
    expect(pollMs({ visible: true, takingOver: false, error: new ApiError(403, "forbidden", "x") })).toBe(false);
    expect(pollMs({ visible: true, takingOver: false, error: new ApiError(404, "not_found", "x") })).toBe(10_000);
    expect(pollMs({ visible: true, takingOver: false, error: new ApiError(503, "unavailable", "x") })).toBe(10_000);
    expect(pollMs({ visible: true, takingOver: false, error: new TypeError("offline") })).toBe(10_000);
  });
});

describe("a click on the shown screenshot", () => {
  it("is scaled to the agent's browser and kept on its screen (its last pixel is one short of its size)", () => {
    const shown = { width: 640, height: 400 };
    expect(scalePoint({ x: 320, y: 200 }, shown, { vw: 1280, vh: 800 })).toEqual({ x: 640, y: 400 });
    expect(scalePoint({ x: 700, y: -5 }, shown, { vw: 1280, vh: 800 })).toEqual({ x: 1279, y: 0 });
    expect(scalePoint({ x: 640, y: 400 }, shown, { vw: 1280, vh: 800 })).toEqual({ x: 1279, y: 799 });
    expect(scalePoint({ x: 1, y: 1 }, { width: 0, height: 0 }, { vw: 1280, vh: 800 })).toBeNull();
  });
});

describe("answers and commands", () => {
  it("send exactly one action each, as one line (control characters become spaces; nothing else is touched)", () => {
    expect(answer.text(" 48 29\n13 ")).toEqual({ text: " 48 29 13 " });
    expect(answer.text("a  b\tc")).toEqual({ text: "a  b c" });
    expect(answer.text("x".repeat(300))).toEqual({ text: "x".repeat(200) });
    expect(answer.option(1)).toEqual({ option: 1 });
    expect(answer.point({ x: 640, y: 212 }, "Citizen Login")).toEqual({ x: 640, y: 212, text: "Citizen Login" });
    expect(answer.point({ x: 640, y: 212 }, "  Citizen\n Login ")).toEqual({ x: 640, y: 212, text: "Citizen Login" });
    expect(answer.point({ x: 1, y: 2 })).toEqual({ x: 1, y: 2 });
    expect([answer.skip(), answer.takeover(), answer.done(), answer.ok(false)]).toEqual([{ skip: true }, { takeover: true }, { done: true }, { ok: false }]);
  });

  it("type into a password box as a secret, and when the person asks to hide it", () => {
    const [w] = cleanPending(pending([takeover()])).items;
    const password = w.fields.find((f) => f.type === "password") ?? null;
    expect(command.type("Clerk@123", { hide: false, box: password })).toEqual({ kind: "type", text: "Clerk@123", secret: true, replace: false });
    expect(command.type("98", { hide: true, box: null, replace: true })).toEqual({ kind: "type", text: "98", secret: true, replace: true });
    expect(command.type("98", { hide: false, box: w.fields[0] })).toMatchObject({ secret: false });
    expect([command.press("Enter"), command.back(), command.scroll()]).toEqual([{ kind: "press", key: "Enter" }, { kind: "back" }, { kind: "scroll", dy: 400 }]);
    expect(command.scroll(-400)).toEqual({ kind: "scroll", dy: -400 });
  });

  it("type a password exactly as it was typed: no trimming, no collapsed spaces", () => {
    expect(command.type("  pa  ss ", { hide: true, box: null })).toMatchObject({ text: "  pa  ss " });
    expect(command.type("a\tb\u0000c", { hide: true, box: null })).toMatchObject({ text: "a b c" });
  });

  it("open only addresses on the portal", () => {
    expect(portalPath(" /apply ")).toBe("/apply");
    expect(portalPath("@department/queue")).toBe("@department/queue");
    expect(portalPath("/a.b/c..d?x=1")).toBe("/a.b/c..d?x=1");
    for (const bad of ["https://evil.example/", "apply", "", "/a\nb", `/${"a".repeat(400)}`]) expect(portalPath(bad)).toBeNull();
  });

  it("refuse the addresses the server refuses: another host, a backslash, a step up", () => {
    const bad = ["//evil.example/x", "/\\evil.example", "/a\\b", "/../etc", "/a/../b", "/a/..", "/./x", "/%2e%2e/x", "/a/%2E%2E/b", "/a%2f%2fb", "/a%5Cb", "@dept//q", "/x//y"];
    for (const path of bad) expect(portalPath(path), path).toBeNull();
  });

  it("knows which answers each question takes, as the server does", () => {
    expect(takes("takeover", "done") && takes("takeover", "skip") && !takes("takeover", "text")).toBe(true);
    expect(takes("navigate", "point") && takes("navigate", "takeover") && !takes("navigate", "ok")).toBe(true);
    expect(takes("confirm", "ok") && takes("confirm", "option") && !takes("confirm", "text")).toBe(true);
    expect(takes("otp", "text") && !takes("otp", "option")).toBe(true);
  });

  it("says what was sent in words, never the text typed", () => {
    expect(commandWords(command.press("Enter"))).toBe("Sent: Enter");
    expect(commandWords(command.back())).toBe("Sent: Back");
    expect(commandWords(command.scroll())).toBe("Sent: Scroll down");
    expect(commandWords(command.scroll(-400))).toBe("Sent: Scroll up");
    expect(commandWords(command.click({ x: 640, y: 400 }))).toBe("Sent: click at (640, 400)");
    expect(commandWords(command.goto("/apply"))).toBe("Sent: open /apply");
    const typed = commandWords(command.type("Clerk@123", { hide: true, box: null }));
    expect(typed).toBe("Sent: typed 9 characters");
    expect(commandWords(command.type("x", { hide: true, box: null }))).toBe("Sent: typed 1 character");
    expect(typed).not.toContain("Clerk");
  });

  it("knows which commands leave the selected box behind", () => {
    expect(movesFocus(command.click({ x: 1, y: 1 }))).toBe(true);
    expect(movesFocus(command.press("Tab"))).toBe(true);
    expect(movesFocus(command.press("Enter"))).toBe(true);
    expect(movesFocus(command.goto("/apply"))).toBe(true);
    expect(movesFocus(command.back())).toBe(true);
    expect(movesFocus(command.press("Backspace"))).toBe(false);
    expect(movesFocus(command.scroll())).toBe(false);
    expect(movesFocus(command.type("a", { hide: true, box: null }))).toBe(false);
  });
});
