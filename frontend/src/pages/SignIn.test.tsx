import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { SignIn } from "./SignIn";

function envelope(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

function mount(fetchMock: typeof fetch) {
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/sign-in"]}>
        <SignIn />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SignIn", () => {
  it("asks for both fields and lets the browser's password manager fill them", () => {
    const fetchMock = vi.fn(() => envelope(200, { ok: true, data: { status: "ok", owner_configured: true } }));
    mount(fetchMock as unknown as typeof fetch);
    const email = screen.getByLabelText("Email");
    const password = screen.getByLabelText("Password");
    expect(email).toBeRequired();
    expect(password).toBeRequired();
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("shows the server's message when the credentials are wrong", async () => {
    const fetchMock = vi.fn((url: string, _init?: RequestInit) =>
      String(url).includes("/auth/login")
        ? envelope(401, { ok: false, error: { code: "bad_credentials", message: "That email and password do not match" } })
        : envelope(200, { ok: true, data: { status: "ok", owner_configured: true } }),
    );
    mount(fetchMock as unknown as typeof fetch);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "owner@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong-password" } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("That email and password do not match"));
    const [, init] = fetchMock.mock.calls.find((c) => String(c[0]).includes("/auth/login"))!;
    expect(new Headers(init?.headers).get("X-Requested-With")).toBe("AgentQA");   // the CSRF header on every POST
  });

  it("tells the owner how to create the first account", async () => {
    const fetchMock = vi.fn(() => envelope(200, { ok: true, data: { status: "ok", owner_configured: false } }));
    mount(fetchMock as unknown as typeof fetch);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("owner-set"));
  });
});
