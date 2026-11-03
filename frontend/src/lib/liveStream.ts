/** One run's event stream over Server-Sent Events: frames are validated before they touch the reducer, a dropped
 *  connection is reported and retried from the last cursor (the server then sends only what is new), and the
 *  reducer ignores anything replayed. */
import { useEffect, useReducer, useRef, useState } from "react";
import { api, type LiveEvent } from "./api";
import { initialLiveState, reduceLive, type LiveState } from "./live";

export type StreamStatus = "idle" | "live" | "retrying" | "ended";
const RETRY_MS = 3000;

interface Frame {
  events: LiveEvent[];
  cursor?: string;
}

function isEvent(x: unknown): x is LiveEvent {
  if (!x || typeof x !== "object") return false;
  const e = x as Record<string, unknown>;
  return typeof e.agent === "string" && typeof e.kind === "string" && typeof e.title === "string" && typeof e.seq === "number" && typeof e.w === "string" && typeof e.t === "number";
}

/** The frame, or null when it is not JSON or not shaped like one: a bad frame is skipped, never dispatched. */
export function parseFrame(data: string): Frame | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const { events, cursor } = parsed as Record<string, unknown>;
  if (!Array.isArray(events) || !events.every(isEvent)) return null;
  return { events, cursor: typeof cursor === "string" ? cursor : undefined };
}

export function useLiveStream(slug: string, session: string): { state: LiveState; status: StreamStatus } {
  const [state, dispatch] = useReducer(reduceLive, initialLiveState);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const cursor = useRef("");

  useEffect(() => {
    if (!session) return;
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const open = () => {
      const url = api.streamUrl(slug, session) + (cursor.current ? `?cursor=${encodeURIComponent(cursor.current)}` : "");
      source = new EventSource(url);
      source.addEventListener("live", (e) => {
        const frame = parseFrame((e as MessageEvent<string>).data);
        if (!frame) return;
        if (frame.cursor) cursor.current = frame.cursor;
        dispatch({ type: "events", events: frame.events, cursor: frame.cursor });
        setStatus("live");
      });
      source.addEventListener("end", () => {
        dispatch({ type: "end" });
        setStatus("ended");
        source?.close();
      });
      source.addEventListener("error", () => {
        source?.close();
        if (stopped) return;
        setStatus("retrying");
        timer = setTimeout(open, RETRY_MS);
      });
    };
    open();
    return () => {
      stopped = true;
      clearTimeout(timer);
      source?.close();
    };
  }, [slug, session]);

  return { state, status };
}
