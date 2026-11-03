import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ProjectList } from "./ProjectList";

afterEach(cleanup);

function mount(props: Partial<Parameters<typeof ProjectList>[0]>) {
  return render(
    <MemoryRouter>
      <ProjectList projects={undefined} isPending={false} isError={false} hrefFor={(slug) => `/projects/${slug}`} emptyText="Nothing here yet." {...props} />
    </MemoryRouter>,
  );
}

describe("ProjectList", () => {
  it("announces loading as a status, not as an empty list", () => {
    mount({ isPending: true });
    expect(screen.getByRole("status")).toHaveTextContent(/Loading/);
    expect(screen.queryByText("Nothing here yet.")).toBeNull();
  });

  it("shows an error, never the empty text, when the list could not be loaded", () => {
    mount({ isError: true });
    expect(screen.getByRole("alert")).toHaveTextContent(/could not be loaded/);
    expect(screen.queryByText("Nothing here yet.")).toBeNull();
  });

  it("shows the empty text with a way to add a project only when the list is really empty", () => {
    mount({ projects: [] });
    expect(screen.getByText(/Nothing here yet/)).toBeVisible();
    expect(screen.getByRole("link", { name: "New project" })).toHaveAttribute("href", "/projects/new");
  });

  it("links each project where the page asks", () => {
    mount({ projects: [{ slug: "demo", name: "Demo", url: "http://127.0.0.1:8800", environment: "Test / QA", cases: 3, defects: 1 } as never] });
    expect(screen.getByRole("link", { name: /Demo/ })).toHaveAttribute("href", "/projects/demo");
  });
});
