import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import type { GateCounts } from "../../lib/gatesApi";
import { demoBoard, demoModel } from "../../test-fixtures/live";
import { demo } from "../../test-fixtures/gates";
import { PipelineCard } from "./LiveHeader";

afterEach(cleanup);

function mount(now: GateCounts | null) {
  render(
    <MemoryRouter>
      <PipelineCard model={demoModel()} def={demoBoard} runOver slug="demo" now={now} onJump={() => {}} />
    </MemoryRouter>,
  );
}

describe("PipelineCard gates", () => {
  it("link to their pages and, for the newest run, say what is still open", () => {
    mount({ ...demo().gates, questions_open: 3, defects_draft: 2 });
    expect(screen.getByRole("link", { name: /Questions for you.*asked · 3 open/ })).toHaveAttribute("href", "/projects/demo/questions");
    expect(screen.getByRole("link", { name: /Test plan approval.*approved/ })).toHaveAttribute("href", "/projects/demo/plan");
    expect(screen.getByRole("link", { name: /Defects to confirm.*found · 2 to confirm/ })).toHaveAttribute("href", "/projects/demo/defects");
  });

  it("keep the recording's words for an older run", () => {
    mount(null);
    expect(screen.getByRole("link", { name: /Questions for you/ })).not.toHaveTextContent(/open/);
  });
});
