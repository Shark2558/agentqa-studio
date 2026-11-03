/** A fetch stub for component tests: routes keyed by "METHOD /path" (the /api/v1 prefix and the query are dropped),
 *  answering with the API envelope. A route may be a function of the request to inspect or echo the body. */
import { vi } from "vitest";

export type Routes = Record<string, unknown>;
const JSON_HEADERS = { "Content-Type": "application/json" };
const FAIL = Symbol("fail");
type Failure = { [FAIL]: true; status: number; code: string; message: string };

/** A route value that answers with an error envelope. */
export function fail(status: number, code: string, message: string): Failure {
  return { [FAIL]: true, status, code, message };
}

const errorResponse = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ ok: false, error: { code, message } }), { status, headers: JSON_HEADERS });

export function stubFetch(routes: Routes) {
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    const key = `${method} ${url.replace(/^\/api\/v1/, "").split("?")[0]}`;
    if (!(key in routes)) return errorResponse(404, "not_found", `no stub for ${key}`);
    const hit = routes[key];
    const data = typeof hit === "function" ? (hit as (init: RequestInit) => unknown)(init) : hit;
    if (typeof data === "object" && data !== null && FAIL in data) {
      const f = data as Failure;
      return errorResponse(f.status, f.code, f.message);
    }
    return new Response(JSON.stringify({ ok: true, data }), { status: 200, headers: JSON_HEADERS });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

/** The parsed JSON body of the first call matching method and path, or undefined. */
export function sentBody(fn: ReturnType<typeof stubFetch>, method: string, path: string): unknown {
  const call = fn.mock.calls.find(([url, init]) => (init?.method ?? "GET").toUpperCase() === method && String(url).endsWith(path));
  return call?.[1]?.body ? JSON.parse(String(call[1].body)) : undefined;
}
