import { describe, expect, it } from "vitest";
import { toEvent, type LiveEvent } from "./event";
import { emptyMap, foldMap, layoutMap } from "./siteMap";

let seq = 0;
function nav(path: string, extra: Record<string, unknown> = {}): LiveEvent {
  seq += 1;
  return toEvent({ t: seq, seq, w: "main", agent: "explorer", kind: "navigate", title: `Opened ${path}`, phase: "action", path, ...extra }) as LiveEvent;
}

describe("site map: screens by click depth", () => {
  it("places screens by depth (given, or one below the parent) and joins them to their parent", () => {
    const m = foldMap(emptyMap, [nav("/", { depth: 0, role: "citizen", status: 200 }), nav("/apply", { parent: "/", role: "citizen" }), nav("/apply/step2?x=1", { parent: "/apply" })]);
    expect(m.order).toEqual(["/", "/apply", "/apply/step2"]);
    expect(m.nodes.get("/apply")?.depth).toBe(1);
    expect(m.nodes.get("/apply/step2")?.depth).toBe(2);
    expect(m.current).toBe("/apply/step2");
    const layout = layoutMap(m);
    expect(layout.edges).toEqual([{ from: "/", to: "/apply" }, { from: "/apply", to: "/apply/step2" }]);
    expect(layout.nodes.map((n) => n.x)).toEqual([16, 230, 444]);
  });

  it("collects which roles reached a screen and keeps an HTTP error", () => {
    const m = foldMap(emptyMap, [nav("/admin", { role: "admin", status: 200 }), nav("/admin", { role: "clerk", status: 500 })]);
    expect(m.nodes.get("/admin")).toMatchObject({ roles: ["admin", "clerk"], status: 500 });
  });

  it("a probe or another agent's visit only moves the current screen", () => {
    const m = foldMap(emptyMap, [nav("/"), nav("/", { probe: true }), { ...nav("/secret"), agent: "executor" } as LiveEvent]);
    expect(m.order).toEqual(["/"]);
  });

  it("treats a path named __proto__ as just another screen", () => {
    const m = foldMap(emptyMap, [nav("__proto__"), nav("constructor")]);
    expect(m.order).toEqual(["__proto__", "constructor"]);
    expect(layoutMap(m).nodes).toHaveLength(2);
  });
});
