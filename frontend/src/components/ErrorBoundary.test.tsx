import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ErrorBoundary } from "./ErrorBoundary";

function Panel({ broken }: { broken: boolean }) {
  if (broken) throw new Error("bad event");
  return <p>panel is fine</p>;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("shows a message in place of a broken part and keeps the rest", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<div><ErrorBoundary><Panel broken /></ErrorBoundary><p>still here</p></div>);
    expect(screen.getByRole("alert")).toHaveTextContent("could not be shown");
    expect(screen.getByText("still here")).toBeInTheDocument();
  });

  it("tries the part again when its reset key changes (the replay moved on)", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { rerender } = render(<ErrorBoundary resetKey={1}><Panel broken /></ErrorBoundary>);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    rerender(<ErrorBoundary resetKey={1}><Panel broken={false} /></ErrorBoundary>);
    expect(screen.getByRole("alert")).toBeInTheDocument();            // same key: stays down
    rerender(<ErrorBoundary resetKey={2}><Panel broken={false} /></ErrorBoundary>);
    expect(screen.getByText("panel is fine")).toBeInTheDocument();
  });

  it("a part still broken under the new key shows the message again and stays down until the key moves on", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { rerender } = render(<ErrorBoundary resetKey={1}><Panel broken /></ErrorBoundary>);
    rerender(<ErrorBoundary resetKey={2}><Panel broken /></ErrorBoundary>);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    rerender(<ErrorBoundary resetKey={2}><Panel broken={false} /></ErrorBoundary>);
    expect(screen.getByRole("alert")).toBeInTheDocument();            // same key: no retry
    rerender(<ErrorBoundary resetKey={3}><Panel broken={false} /></ErrorBoundary>);
    expect(screen.getByText("panel is fine")).toBeInTheDocument();
  });
});
