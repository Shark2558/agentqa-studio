import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";
import { demo, renderPage } from "../test-fixtures/gates";
import { NavLinks } from "./NavLinks";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("NavLinks", () => {
  it("gives every gate's link a spoken count of what waits", async () => {
    const d = demo();
    d.gates.plan = { ...d.gates.plan, approved: false, proposed: 206 };
    renderPage(<NavLinks slug="demo" />, "/", "/", { "GET /projects/demo/gates": d.gates });
    // accessible-name queries over the whole list are slow when other test files run beside this one
    expect(await screen.findByRole("link", { name: "Questions, 15 open" }, { timeout: 5_000 })).toHaveAttribute("href", "/projects/demo/questions");
    expect(screen.getByRole("link", { name: "Test plan, 206 to review" })).toHaveAttribute("href", "/projects/demo/plan");
    expect(screen.getByRole("link", { name: "Defects, 19 to confirm" })).toHaveAttribute("href", "/projects/demo/defects");
    expect(screen.getByRole("link", { name: "Change log" })).toHaveAttribute("href", "/projects/demo/changes");
  });

  it("lists Visual review and Heals with what waits there (Phase C)", async () => {
    const d = demo();
    d.gates = { ...d.gates, visual_changed: 2, heals_proposed: 1 };
    renderPage(<NavLinks slug="demo" />, "/", "/", { "GET /projects/demo/gates": d.gates });
    expect(await screen.findByRole("link", { name: "Visual review, 2 changed" }, { timeout: 5_000 })).toHaveAttribute("href", "/projects/demo/visual");
    expect(screen.getByRole("link", { name: "Heals, 1 to review" })).toHaveAttribute("href", "/projects/demo/heals");
  });

  it("names the links plainly when nothing waits or the counts cannot be read", async () => {
    renderPage(<NavLinks slug="demo" />, "/", "/", {});
    expect(await screen.findByRole("link", { name: "Questions" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Test plan" })).toBeInTheDocument();
  });

  it("lists no project pages outside a project", () => {
    renderPage(<NavLinks slug={null} />, "/", "/", {});
    expect(screen.queryByRole("link", { name: /Questions/ })).toBeNull();
    expect(screen.getByRole("link", { name: "Live View" })).toHaveAttribute("href", "/live");
  });
});
