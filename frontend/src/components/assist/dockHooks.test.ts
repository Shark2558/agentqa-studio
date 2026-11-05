import { afterEach, describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";
import type { Waiting } from "../../lib/assist";
import { forgetAnnounced, useNews } from "./dockHooks";

const question = (id: number, text: string): Waiting => ({
  id, kind: "navigate", role: "citizen", agent: "explorer", at: null, full: true, question: text, hint: "", options: [],
  clickables: [], fields: [], secret: false, url: "", vw: 0, vh: 0, headed: false, log: [], shotV: 0, hasShot: false,
  production: false,
});

afterEach(() => forgetAnnounced());

describe("useNews", () => {
  it("settles when the caller hands a new empty list on every render (nothing loaded yet)", () => {
    const { result, rerender } = renderHook(() => useNews("demo", [], true, true));
    rerender();
    expect(result.current).toBe("");
  });

  it("says a question in another project even when its number is the same", () => {
    const { result, rerender } = renderHook(({ slug, text }) => useNews(slug, [question(7, text)], true, true),
      { initialProps: { slug: "a", text: "First project?" } });
    expect(result.current).toBe("The explorer (as citizen) needs you: First project?");
    rerender({ slug: "b", text: "Second project?" });
    expect(result.current).toBe("The explorer (as citizen) needs you: Second project?");
  });
});
