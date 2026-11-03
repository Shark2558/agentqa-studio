import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { StepAccounts } from "./StepAccounts";

afterEach(cleanup);

const clerk = { role: "clerk", login_option: "Department Login", method: "password", username: "clerk1", password: "Clerk@123" };

describe("StepAccounts", () => {
  it("keeps the password in a password box and passes edits up", () => {
    const onRole = vi.fn();
    render(<StepAccounts noLogin={false} roles={[clerk]} onNoLogin={vi.fn()} onRole={onRole} onAdd={vi.fn()} onRemove={vi.fn()} />);
    const pw = screen.getByLabelText("Password");
    expect(pw).toHaveAttribute("type", "password");
    expect(screen.queryByText("Clerk@123")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Role name"), { target: { value: "officer" } });
    expect(onRole).toHaveBeenCalledWith(0, { ...clerk, role: "officer" });
  });

  it("asks for a mobile number and an OTP source for mobile OTP logins", () => {
    render(<StepAccounts noLogin={false} roles={[{ role: "citizen", login_option: "Citizen Login", method: "mobile_otp" }]} onNoLogin={vi.fn()} onRole={vi.fn()} onAdd={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByLabelText("Mobile number")).toBeInTheDocument();
    expect(screen.getByLabelText("Where the OTP comes from")).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("hides the accounts when no login is needed", () => {
    const onNoLogin = vi.fn();
    render(<StepAccounts noLogin={true} roles={[clerk]} onNoLogin={onNoLogin} onRole={vi.fn()} onAdd={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.queryByLabelText("Role name")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/No login needed/));
    expect(onNoLogin).toHaveBeenCalledWith(false);
  });
});
