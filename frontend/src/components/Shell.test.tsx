import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { Shell } from "./Shell";

function envelope(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify({ ok: true, data: body }), { status: 200, headers: { "Content-Type": "application/json" } }));
}

/** The shell exactly as App.tsx mounts it: the element of the parent `/*` route, with the pages as nested routes. */
function mount(path: string) {
  vi.stubGlobal("fetch", vi.fn(() => envelope({ email: "owner@example.com", role: "owner" })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/*"
            element={
              <Shell>
                <Routes>
                  <Route index element={<p>projects page</p>} />
                  <Route path="projects/new" element={<p>wizard</p>} />
                  <Route path="projects/:slug" element={<p>project page</p>} />
                  <Route path="projects/:slug/live" element={<p>live page</p>} />
                </Routes>
              </Shell>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const sidebar = () => screen.getByRole("navigation", { name: "Main" });
const liveLink = (root: HTMLElement) => within(root).getByRole("link", { name: "Live View" });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Shell navigation", () => {
  it("inside a project, Live View goes to that project's live page", () => {
    mount("/projects/demo");
    expect(liveLink(sidebar())).toHaveAttribute("href", "/projects/demo/live");
  });

  it("outside a project (home and the wizard), Live View goes to the project picker", () => {
    mount("/");
    expect(liveLink(sidebar())).toHaveAttribute("href", "/live");
    cleanup();
    mount("/projects/new");
    expect(liveLink(sidebar())).toHaveAttribute("href", "/live");
  });

  it("the brand link is not announced as the current page on an inner page", () => {
    mount("/projects/demo");
    const brand = within(sidebar()).getByRole("link", { name: /AgentQA Studio/ });
    expect(brand).not.toHaveAttribute("aria-current");
  });
});

describe("Shell phone drawer", () => {
  it("opens a dialog with the navigation, the account and Sign out, and makes the page behind it inert", async () => {
    mount("/");
    const menu = screen.getByRole("button", { name: "Menu" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    const drawer = screen.getByRole("dialog", { name: "Menu" });
    expect(liveLink(drawer)).toHaveAttribute("href", "/live");
    expect(within(drawer).getByRole("button", { name: "Sign out" })).toBeVisible();
    expect(await within(drawer).findByText("owner@example.com")).toBeVisible();
    expect(screen.getByRole("main")).toHaveAttribute("inert");
    expect(sidebar()).toHaveAttribute("inert");
  });

  it("Escape closes it from anywhere on the page and focus returns to the menu button", () => {
    mount("/");
    const menu = screen.getByRole("button", { name: "Menu" });
    fireEvent.click(menu);
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull();
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(document.activeElement).toBe(menu);
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");
  });

  it("choosing a link in the drawer closes it", () => {
    mount("/");
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    fireEvent.click(liveLink(screen.getByRole("dialog", { name: "Menu" })));
    expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull();
  });
});

describe("Shell: the AI page", () => {
  it("inside a project, the sidebar links to that project's AI page", () => {
    mount("/projects/demo");
    expect(within(sidebar()).getByRole("link", { name: "AI" })).toHaveAttribute("href", "/projects/demo/ai");
  });
});
