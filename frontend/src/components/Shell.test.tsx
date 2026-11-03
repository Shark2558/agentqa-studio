import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Shell navigation", () => {
  it("inside a project, Live View goes to that project's live page", () => {
    mount("/projects/demo");
    const link = screen.getByRole("navigation", { name: "Main" }).querySelector('a[href="/projects/demo/live"]');
    expect(link).not.toBeNull();
    expect(link).toHaveTextContent("Live View");
  });

  it("outside a project (home and the wizard), Live View goes to the project picker", () => {
    mount("/");
    expect(screen.getByRole("navigation", { name: "Main" }).querySelector('a[href="/live"]')).toHaveTextContent("Live View");
    cleanup();
    mount("/projects/new");
    expect(screen.getByRole("navigation", { name: "Main" }).querySelector('a[href="/live"]')).toHaveTextContent("Live View");
  });
});

describe("Shell phone drawer", () => {
  it("the menu button opens a drawer holding the navigation, and Escape closes it and returns focus", () => {
    mount("/");
    const menu = screen.getByRole("button", { name: "Menu" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    const drawer = screen.getByRole("dialog", { name: "Menu" });
    expect(drawer.querySelector('a[href="/live"]')).toHaveTextContent("Live View");
    fireEvent.keyDown(drawer, { key: "Escape" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(document.activeElement).toBe(menu);
  });

  it("choosing a link in the drawer closes it", () => {
    mount("/");
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    const drawer = screen.getByRole("dialog", { name: "Menu" });
    fireEvent.click(drawer.querySelector('a[href="/live"]')!);
    expect(screen.getByRole("button", { name: "Menu" })).toHaveAttribute("aria-expanded", "false");
  });
});
