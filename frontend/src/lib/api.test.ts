import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, request } from "./api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("unwraps the envelope on success", async () => {
    mockFetch(200, { ok: true, data: { status: "ok" } });
    expect(await request<{ status: string }>("/health")).toEqual({ status: "ok" });
  });

  it("turns an error envelope into an ApiError with the code", async () => {
    mockFetch(401, { ok: false, error: { code: "unauthenticated", message: "Sign in first" } });
    await expect(api.me()).rejects.toMatchObject({ status: 401, code: "unauthenticated" } satisfies Partial<ApiError>);
  });

  it("sends the CSRF header and JSON body on state-changing calls only", async () => {
    const fn = mockFetch(200, { ok: true, data: { email: "o@x.io", role: "owner" } });
    await api.login("o@x.io", "pw");
    const [, init] = fn.mock.calls[0] as unknown as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("X-Requested-With")).toBe("AgentQA");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.credentials).toBe("same-origin");

    await api.projects();
    const [, getInit] = fn.mock.calls[1] as unknown as [string, RequestInit];
    expect(new Headers(getInit.headers).has("X-Requested-With")).toBe(false);
  });
});
