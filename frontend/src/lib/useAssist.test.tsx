import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { stubFetch } from "../test-fetch";
import { pending, waiting } from "../test-fixtures/assist";
import { closeAssist, openAssist, useAssist, useOpenAssist } from "./useAssist";

const ASK = "GET /projects/demo/assist";
const asked = (fetch: ReturnType<typeof stubFetch>) => fetch.mock.calls.filter(([url]) => String(url).endsWith("/assist")).length;

function Probe({ poll, label }: { poll?: boolean; label: string }) {
  const count = useAssist("demo", { poll }).data?.items.length;
  return <p>{`${label}: ${count ?? "none"}`}</p>;
}

function mountProbes(...probes: { poll?: boolean; label: string }[]) {
  const fetch = stubFetch({ [ASK]: pending([waiting(), waiting({ id: 8 })]) });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{probes.map((p) => <Probe key={p.label} {...p} />)}</QueryClientProvider>);
  return { fetch, client };
}

afterEach(() => {
  act(() => closeAssist());
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("which question is open", () => {
  it("is remembered for one project only: another project with the same number does not open", () => {
    const demo = renderHook(() => useOpenAssist("demo"));
    const other = renderHook(() => useOpenAssist("other"));
    act(() => openAssist("demo", 7));
    expect(demo.result.current).toBe(7);
    expect(other.result.current).toBeNull();
    act(() => closeAssist());
    expect(demo.result.current).toBeNull();
  });
});

describe("asking what waits", () => {
  it("is done in one place: the readers share the answer without asking again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { fetch } = mountProbes({ poll: true, label: "dock" }, { label: "banner" }, { label: "live" });
    await waitFor(() => expect(screen.getByText("live: 2")).toBeInTheDocument());
    expect(screen.getByText("banner: 2")).toBeInTheDocument();
    const first = asked(fetch);
    await act(() => vi.advanceTimersByTimeAsync(2_100));
    expect(asked(fetch)).toBe(first + 1);
  });

  it("has exactly one asker per project in the query cache", async () => {
    const { client } = mountProbes({ poll: true, label: "dock" }, { label: "banner" }, { label: "live" });
    await waitFor(() => expect(screen.getByText("dock: 2")).toBeInTheDocument());
    const observers = client.getQueryCache().find({ queryKey: ["assist", "demo"] })?.observers ?? [];
    expect(observers).toHaveLength(3);
    expect(observers.filter((o) => o.options.refetchInterval !== false)).toHaveLength(1);
  });

  it("still loads the list once for a reader that has no asker beside it", async () => {
    const { fetch } = mountProbes({ label: "banner" });
    await waitFor(() => expect(screen.getByText("banner: 2")).toBeInTheDocument());
    expect(asked(fetch)).toBe(1);
  });
});
