import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { WhyButton } from "./ReasonDialog";

afterEach(cleanup);

describe("WhyButton", () => {
  it("does not wear the wizard's explanation-box class (sitting 1, S4)", () => {
    // wizard.css styles `.why` as a box with a blue left rule, and every stylesheet loads on every page: a wrapper
    // called `.why` gave each "Reject" and "Back to review" a stray blue bar. (Vitest reads `?raw` CSS as empty, so the
    // test names the class rather than parsing wizard.css.)
    render(<WhyButton label="Reject" title="Reject 1 case: why?" confirmLabel="Reject 1 case" onConfirm={vi.fn()} />);
    const wrapper = screen.getByRole("button", { name: "Reject" }).parentElement;
    expect(wrapper).toHaveClass("why-button");
    expect(wrapper).not.toHaveClass("why");
  });

  it("asks why first, then decides with the reason", () => {
    const onConfirm = vi.fn();
    render(<WhyButton label="Reject" title="Reject 1 case: why?" confirmLabel="Reject 1 case" onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.change(screen.getByRole("textbox", { name: /Why\?/ }), { target: { value: "checked by hand" } });
    fireEvent.click(screen.getByRole("button", { name: "Reject 1 case" }));
    expect(onConfirm).toHaveBeenCalledWith("checked by hand");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
