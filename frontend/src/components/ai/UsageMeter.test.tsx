import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { Usage } from "../../lib/ai";
import { UsageMeter } from "./UsageMeter";

afterEach(cleanup);

const usage = (over: Omit<Partial<Usage>, "budget"> & { budget?: Partial<Usage["budget"]> }): Usage => ({
  month: "2026-11", prices_dated: "2026-11-03", total_usd: 0.7, calls: 3, estimated: false,
  agents: [{ agent: "req_writer", calls: 3, cost_usd: 0.7, input_tokens: 100000, output_tokens: 50000, estimated: false, last_at: "2026-11-03T10:00:00" }],
  runs: [{ pipeline: "P-1", calls: 3, cost_usd: 0.7, input_tokens: 100000, output_tokens: 50000, estimated: false, last_at: "2026-11-03T10:00:00" }],
  ...over,
  budget: { month: "2026-11", spent: 0.7, cap: 10, pct: 7, alert_at_pct: 80, state: "ok", ...over.budget },
});

describe("UsageMeter", () => {
  it("shows the month's figure per agent and per run with no banner while the budget is fine", () => {
    render(<UsageMeter usage={usage({})} labels={{ req_writer: "Requirement Writer" }} />);
    expect(screen.getByText("$0.70 of $10.00 used this month")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "7");
    expect(screen.getByText("Requirement Writer")).toBeInTheDocument();
    expect(screen.getByText("P-1")).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("warns at the alert percentage and shouts at the cap", () => {
    render(<UsageMeter usage={usage({ total_usd: 8.2, budget: { spent: 8.2, pct: 82, state: "warning" } })} />);
    expect(screen.getByRole("status")).toHaveTextContent(/82 % of the \$10\.00 monthly budget is used/);
    cleanup();
    render(<UsageMeter usage={usage({ total_usd: 10, budget: { spent: 10, pct: 100, state: "capped" } })} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/used up/);
  });

  it("flags estimated figures and says when nothing was spent", () => {
    render(<UsageMeter usage={usage({ total_usd: 0, calls: 0, agents: [], runs: [], budget: { spent: 0, pct: 0 } })} />);
    expect(screen.getByText(/No AI call has cost anything this month/)).toBeInTheDocument();
    cleanup();
    render(<UsageMeter usage={usage({ estimated: true })} />);
    expect(screen.getByText(/estimated/)).toBeInTheDocument();
  });
});
