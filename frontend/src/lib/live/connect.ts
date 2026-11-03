/** The live connection (M1.3, PRD FR-LIVE-7): a WebSocket first, Server-Sent Events when the socket cannot open (an
 *  older browser or proxy; remembered for the tab once SSE has worked). Either way a dropped connection is retried from
 *  the last cursor, so nothing is read twice or missed (the stream's merge also drops repeats), waiting longer after
 *  each failed try (3 s doubling to a minute, with jitter) and giving up after eight ("lost"). The server ends with a
 *  reason; a socket it refuses closes with a code (routes_live_ws.py): 4401 the sign-in ended and 4404 the run is gone
 *  (no retry), 4429 too busy (10 s), 4403 the page's origin (SSE instead), 4400 and 1008 a request it will never take
 *  ("lost"). EventSource hides the HTTP status, so after an SSE error the events endpoint is asked once why. Frames are
 *  checked before anything is handed on. */

export type Transport = "websocket" | "sse";
export type ConnStatus = "connecting" | "live" | "retrying" | "ended" | "signed-out" | "gone" | "lost";

export interface Handlers {
  cursor: () => string;
  onEvents: (events: unknown[], cursor: string | undefined) => void;
  onEnd: (reason: string, cursor: string | undefined) => void;
  onStatus: (status: ConnStatus) => void;
  onTransport: (transport: Transport) => void;
}

export const TRANSPORT_KEY = "agentqa.live.transport";
const RETRY_MS = 3_000;
const MAX_RETRY_MS = 60_000;
const BUSY_RETRY_MS = 10_000;
const MAX_ATTEMPTS = 8;
const SIGNED_OUT = 4401;
const GONE = 4404;
const TOO_MANY = 4429;
const WRONG_ORIGIN = 4403;
const NEVER = new Set([4400, 1008, 1009]);        // a request this server will never take: retrying cannot help
const ID = /^(?!\.{1,2}$)[\w.-]{1,128}$/;          // a project slug or run id: one path segment, never "." or ".."

function segment(id: string): string {
  if (!ID.test(id)) throw new Error(`Not a project or run name: ${JSON.stringify(id.slice(0, 40))}`);
  return encodeURIComponent(id);
}

function apiPath(slug: string, session: string, tail: string): string {
  return `/api/v1/projects/${segment(slug)}/live/${segment(session)}/${tail}`;
}

export function liveUrl(transport: Transport, slug: string, session: string, cursor: string): string {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  const path = apiPath(slug, session, transport === "websocket" ? "ws" : "stream") + query;
  return transport === "sse" ? path : `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;
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

/** How long to wait before retry `n` (from 0): 3 s doubling to a minute, ±20 % so many tabs do not retry in step. */
export function backoffMs(n: number): number {
  return Math.round(Math.min(MAX_RETRY_MS, RETRY_MS * 2 ** n) * (0.8 + 0.4 * Math.random()));
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

interface Conn {
  readonly h: Handlers;
  readonly slug: string;
  readonly session: string;
  stopped: boolean;
  timer: ReturnType<typeof setTimeout> | undefined;
  close: () => void;
  current: Transport | null;
  everOpened: boolean;          // a socket opened once: a later failure is a blip, not a browser without WebSocket
  attempts: number;             // failed tries since the last frame
}

/** Hands a checked frame on; true when it ended the stream. Any frame proves the connection works. */
function deliver(c: Conn, frame: Frame | null): boolean {
  if (!frame) return false;
  c.attempts = 0;
  if (frame.type === "live") {
    c.h.onEvents(frame.events, frame.cursor);
    c.h.onStatus("live");
    return false;
  }
  c.h.onEnd(frame.reason, frame.cursor);
  c.h.onStatus("ended");
  return true;
}

function retry(c: Conn, transport: Transport, atLeastMs = 0): void {
  if (c.stopped) return;
  if (c.attempts >= MAX_ATTEMPTS) return c.h.onStatus("lost");
  const ms = Math.max(atLeastMs, backoffMs(c.attempts));
  c.attempts += 1;
  c.h.onStatus("retrying");
  c.timer = setTimeout(() => open(c, transport), ms);
}

function socketClosed(c: Conn, code: number, opened: boolean): void {
  if (code === SIGNED_OUT) return c.h.onStatus("signed-out");
  if (code === GONE) return c.h.onStatus("gone");
  if (NEVER.has(code)) return c.h.onStatus("lost");
  if (code === TOO_MANY) return retry(c, "websocket", BUSY_RETRY_MS);
  if (code === WRONG_ORIGIN || (!opened && !c.everOpened)) return open(c, "sse");
  retry(c, "websocket");
}

function openSocket(c: Conn): void {
  let opened = false;
  let ended = false;
  const ws = new WebSocket(liveUrl("websocket", c.slug, c.session, c.h.cursor()));
  c.close = () => ws.close();
  ws.onopen = () => {
    opened = true;
    c.everOpened = true;
    c.h.onStatus("live");
  };
  ws.onmessage = (e: MessageEvent | { data: string }) => {
    ended = deliver(c, parseFrame(e.data)) || ended;
  };
  ws.onclose = (e: CloseEvent | { code: number }) => {
    if (!c.stopped && !ended) socketClosed(c, e.code, opened);
  };
}

/** The HTTP status of one plain request for the events since the cursor (0 when the network itself is down). */
async function probe(c: Conn): Promise<number> {
  const query = c.h.cursor() ? `?cursor=${encodeURIComponent(c.h.cursor())}` : "";
  try {
    return (await fetch(apiPath(c.slug, c.session, "events") + query, { credentials: "same-origin" })).status;
  } catch {
    return 0;
  }
}

async function sourceFailed(c: Conn): Promise<void> {
  const status = await probe(c);
  if (c.stopped) return;
  if (status === 401) return c.h.onStatus("signed-out");
  if (status === 404) return c.h.onStatus("gone");
  retry(c, "sse", status === 429 ? BUSY_RETRY_MS : 0);
}

function openSource(c: Conn): void {
  const es = new EventSource(liveUrl("sse", c.slug, c.session, c.h.cursor()));
  c.close = () => es.close();
  const take = (type: "live" | "end") => (e: Event) => {
    const frame = parseFrame((e as MessageEvent).data, type);
    if (frame) rememberSse();                             // SSE works here: the tab's next run goes straight to it
    if (deliver(c, frame)) es.close();
  };
  es.addEventListener("live", take("live"));
  es.addEventListener("end", take("end"));
  es.addEventListener("error", () => {
    es.close();
    void sourceFailed(c);
  });
}

function open(c: Conn, transport: Transport): void {
  if (c.stopped) return;
  if (transport !== c.current) c.h.onTransport(transport);   // said once per transport, not on every reconnect
  c.current = transport;
  c.h.onStatus("connecting");
  if (transport === "websocket") openSocket(c);
  else openSource(c);
}

/** Open the live connection for one run; returns `stop`, which closes it and cancels any retry. */
export function connectLive(slug: string, session: string, h: Handlers): () => void {
  const c: Conn = { h, slug, session, stopped: false, timer: undefined, close: () => undefined, current: null, everOpened: false, attempts: 0 };
  open(c, preferred());
  return () => {
    c.stopped = true;
    clearTimeout(c.timer);
    c.close();
  };
}
