import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { RequirementChat } from "./RequirementChat";
import type { ChatResult } from "../../lib/api";

const chat: ChatResult = {
  source: "rules",
  items: [
    { id: "T-001", text: "Reports can be exported.", kind: "requirement", flags: [] },
    { id: "T-002", text: "Export must finish quickly.", kind: "requirement", flags: [{ word: "quickly", why: "no measurable time limit" }] },
  ],
  questions: [{ id: "q1", topic: "roles", question: "Who will use this?" }],
};

afterEach(cleanup);

describe("RequirementChat", () => {
  it("shows what was read, flags vague words and asks its questions", () => {
    render(<RequirementChat chat={chat} answers={{}} confirmed={false} isSaving={false} onAnswer={vi.fn()} onConfirm={vi.fn()} />);
    expect(screen.getByText("Reports can be exported.")).toBeInTheDocument();
    expect(screen.getByText(/“quickly” — no measurable time limit/)).toBeInTheDocument();
    expect(screen.getByLabelText("Who will use this?")).toBeInTheDocument();
    expect(screen.queryByText(/proposed by AI/)).not.toBeInTheDocument();
  });

  it("passes answers up and confirms the list", () => {
    const onAnswer = vi.fn();
    const onConfirm = vi.fn();
    render(<RequirementChat chat={chat} answers={{}} confirmed={false} isSaving={false} onAnswer={onAnswer} onConfirm={onConfirm} />);
    fireEvent.change(screen.getByLabelText("Who will use this?"), { target: { value: "Clerks." } });
    expect(onAnswer).toHaveBeenCalledWith("q1", "Clerks.");
    fireEvent.click(screen.getByRole("button", { name: "Looks right" }));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("says when the list came from AI and when it is already confirmed", () => {
    render(<RequirementChat chat={{ ...chat, source: "ai" }} answers={{}} confirmed={true} isSaving={false} onAnswer={vi.fn()} onConfirm={vi.fn()} />);
    expect(screen.getByText(/proposed by AI/)).toBeInTheDocument();
    expect(screen.getByText("Confirmed and saved")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Looks right" })).not.toBeInTheDocument();
  });
});
