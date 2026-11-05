import { afterEach, describe, expect, it, vi } from "vitest";
import { useLayoutEffect } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { renderPage } from "../test-fixtures/gates";
import { Shell } from "./Shell";

/** The help box stays out of the way (renders nothing) unless a test makes it break. */
const dock = vi.hoisted(() => ({ breaks: false }));
vi.mock("./assist/NeedsYouDock", () => ({
  NeedsYouDock: () => {
    if (dock.breaks) throw new Error("The help box broke");
    return null;
  },
}));

function envelope(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify({ ok: true, data: body }), { status: 200, headers: { "Content-Type": "application/json" } }));
}

/** Stands in for the browser's Back button: it moves the page without going through the drawer. */
function BrowserBack() {
  const navigate = useNavigate();
  return <button type="button" onClick={() => navigate(-1)}>Browser back</button>;
}

/** A project page that reports, from its first frame, whether the phone drawer still covered it. */
function ProjectPage({ onFirstFrame }: { onFirstFrame: (drawerShown: boolean) => void }) {
  useLayoutEffect(() => onFirstFrame(screen.queryByRole("dialog", { name: "Menu" }) !== null), [onFirstFrame]);
  return <p>project page</p>;
}

type MountOptions = { previous?: string; projectPage?: React.ReactNode };

/** The shell exactly as App.tsx mounts it: the element of the parent `/*` route, with the pages as nested routes.
 *  `previous` puts a page before `path` in the history, reachable with the stand-in Back button. */
function mount(path: string, { previous, projectPage = <p>project page</p> }: MountOptions = {}) {
  vi.stubGlobal("fetch", vi.fn(() => envelope({ email: "owner@example.com", role: "owner" })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={previous ? [previous, path] : [path]}>
        {previous && <BrowserBack />}
        <Routes>
          <Route
            path="/*"
            element={
              <Shell>
                <Routes>
                  <Route index element={<p>projects page</p>} />
                  <Route path="projects/new" element={<p>wizard</p>} />
                  <Route path="projects/:slug" element={projectPage} />
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
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  dock.breaks = false;
});

describe("the app frame", () => {
  it("keeps the page when the help box breaks: the box says so in its place and everything else stays", async () => {
    dock.breaks = true;
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderPage(<Shell><h1>The project</h1></Shell>, "/projects/demo", "/projects/:slug", {});
    expect(await screen.findByRole("heading", { name: "The project" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/help box could not be shown/i);
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });
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

  it("going Back (any move that skips the drawer) closes it before the new page shows, not one frame later", () => {
    const onFirstFrame = vi.fn();
    mount("/", { previous: "/projects/demo", projectPage: <ProjectPage onFirstFrame={onFirstFrame} /> });
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
    expect(screen.getByText("project page")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull();
    expect(onFirstFrame).toHaveBeenCalledWith(false);
    expect(onFirstFrame).not.toHaveBeenCalledWith(true);
  });
});

describe("Shell: the AI page", () => {
  it("inside a project, the sidebar links to that project's AI page", () => {
    mount("/projects/demo");
    expect(within(sidebar()).getByRole("link", { name: "AI" })).toHaveAttribute("href", "/projects/demo/ai");
  });
});
