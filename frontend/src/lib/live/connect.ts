/** The live connection (M1.3, PRD FR-LIVE-7): a WebSocket first, Server-Sent Events when the socket cannot open (an
 *  older browser or proxy; remembered for the tab). Either way a dropped connection is retried from the last cursor,
 *  so nothing is read twice or missed (the stream's merge also drops repeats). The server ends with a reason; a socket
 *  it refuses closes with a code: 4401 the sign-in ended, 4404 the run is gone (no retry), 4429 too many open streams
 *  (try again in 10 s). Frames are checked before anything is handed on. */

export type Transport = "websocket" | "sse";
export type ConnStatus = "connecting" | "live" | "retrying" | "ended" | "signed-out" | "gone";

export interface Handlers {
  cursor: () => string;
  onEvents: (events: unknown[], cursor: string | undefined) => void;
  onEnd: (reason: string, cursor: string | undefined) => void;
  onStatus: (status: ConnStatus) => void;
  onTransport: (transport: Transport) => void;
}

export const TRANSPORT_KEY = "agentqa.live.transport";
const RETRY_MS = 3_000;
const BUSY_RETRY_MS = 10_000;
const SIGNED_OUT = 4401;
const GONE = 4404;
const TOO_MANY = 4429;

export function liveUrl(transport: Transport, slug: string, session: string, cursor: string): string {
  const path = `/api/v1/projects/${encodeURIComponent(slug)}/live/${encodeURIComponent(session)}/${transport === "websocket" ? "ws" : "stream"}`;
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  if (transport === "sse") return path + query;
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}${query}`;
}

interface Frame {
  type: "live" | "end";
  events: unknown[];
  cursor?: string;
  reason: string;
}

/** A frame from either transport, or null when it is not JSON or not shaped like one. */
export function parseFrame(data: unknown, type?: "live" | "end"): Frame | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(String(data));
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const f = parsed as Record<string, unknown>;
  const kind = type ?? f.type;
  const cursor = typeof f.cursor === "string" ? f.cursor : undefined;
  if (kind === "end") return { type: "end", events: [], cursor, reason: typeof f.reason === "string" ? f.reason : "finished" };
  if (kind !== "live" || !Array.isArray(f.events)) return null;
  return { type: "live", events: f.events, cursor, reason: "" };
}

function preferred(): Transport {
  try {
    return sessionStorage.getItem(TRANSPORT_KEY) === "sse" ? "sse" : "websocket";
  } catch {
    return "websocket";
  }
}

function rememberSse(): void {
  try {
    sessionStorage.setItem(TRANSPORT_KEY, "sse");
  } catch {
    // storage refused: this tab simply tries the socket again next time
  }
}

/** Open the live connection for one run; returns `stop`, which closes it and cancels any retry. */
export function connectLive(slug: string, session: string, h: Handlers): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let close: () => void = () => undefined;

  const deliver = (frame: Frame | null): boolean => {
    if (!frame) return false;
    if (frame.type === "live") {
      h.onEvents(frame.events, frame.cursor);
      h.onStatus("live");
      return false;
    }
    h.onEnd(frame.reason, frame.cursor);
    h.onStatus("ended");
    return true;
  };
  const retry = (ms: number, transport: Transport) => {
    if (stopped) return;
    h.onStatus("retrying");
    timer = setTimeout(() => open(transport), ms);
  };

  const openSocket = () => {
    let opened = false;
    let ended = false;
    const ws = new WebSocket(liveUrl("websocket", slug, session, h.cursor()));
    close = () => ws.close();
    ws.onopen = () => {
      opened = true;
      h.onStatus("live");
    };
    ws.onmessage = (e: MessageEvent | { data: string }) => {
      ended = deliver(parseFrame(e.data)) || ended;
    };
    ws.onclose = (e: CloseEvent | { code: number }) => {
      if (stopped || ended) return;
      if (e.code === SIGNED_OUT) return h.onStatus("signed-out");
      if (e.code === GONE) return h.onStatus("gone");
      if (e.code === TOO_MANY) return retry(BUSY_RETRY_MS, "websocket");
      if (!opened) {
        rememberSse();
        return open("sse");
      }
      retry(RETRY_MS, "websocket");
    };
  };

  const openSource = () => {
    const es = new EventSource(liveUrl("sse", slug, session, h.cursor()));
    close = () => es.close();
    es.addEventListener("live", (e) => deliver(parseFrame((e as MessageEvent).data, "live")));
    es.addEventListener("end", (e) => {
      if (deliver(parseFrame((e as MessageEvent).data, "end"))) es.close();
    });
    es.addEventListener("error", () => {
      es.close();
      retry(RETRY_MS, "sse");
    });
  };

  let current: Transport | null = null;
  function open(transport: Transport): void {
    if (stopped) return;
    if (transport !== current) h.onTransport(transport);   // said once per transport, not on every reconnect
    current = transport;
    h.onStatus("connecting");
    if (transport === "websocket") openSocket();
    else openSource();
  }

  open(preferred());
  return () => {
    stopped = true;
    clearTimeout(timer);
    close();
  };
}
