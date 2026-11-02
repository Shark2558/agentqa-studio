"""Stand-in for AI provider APIs, to show and test key failover without real keys or cost.

    python -m agentqa demo-ai --port 8950

Paths: /openai/v1 (OpenAI and every OpenAI-compatible provider), /anthropic/v1, /gemini/v1beta and
/azure/openai/deployments/<name>/chat/completions. What happens depends on the key's text:
  ...ratelimit...  429 rate limit (Retry-After: 30)     ...quota...    429 daily quota used up
  ...billing...    429 insufficient_quota (billing)      ...invalid...  401 key rejected
  ...down...       503 service unavailable              ...slow...     answers after 5 s (times out)
  ...garbage...    200 but not JSON                      anything else  a valid JSON answer
and model 'retired-model' answers 404 'model not found'. Every request is counted per key (GET /_calls).

Most answers carry no test content: this server exists to exercise routing, not to stand in for a model. The
one exception is AgentQA's own tagged tasks ([[AQ-TASK:visual-act]], visual-verify, casegen, req-writer), which get a
simple word-overlap answer so the Visual QA and test case agents can be exercised end to end without a real
model. It is a heuristic, not reasoning, and a key containing 'liar' answers verify with a quote that is not on
the page (to show that such a verdict is refused).
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CALLS: dict[str, int] = {}
LOCK = threading.Lock()
MODELS = ["gpt-4o-mini", "gpt-4o", "claude-sonnet-5-5", "claude-haiku-5-5", "gemini-2.5-flash", "gemini-2.5-pro",
          "deepseek-chat", "llama-3.3-70b-versatile", "mistral-small-latest"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _key(self) -> str:
        auth = self.headers.get("Authorization", "")
        return (self.headers.get("x-api-key") or self.headers.get("x-goog-api-key") or self.headers.get("api-key")
                or (auth[7:] if auth.lower().startswith("bearer ") else ""))

    def _send(self, code: int, obj, headers: dict | None = None, raw: str | None = None):
        data = (raw if raw is not None else json.dumps(obj)).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _fault(self, key: str) -> bool:
        with LOCK:
            CALLS[key] = CALLS.get(key, 0) + 1
        key = key.lower()
        if "ratelimit" in key:
            self._send(429, {"error": {"type": "rate_limit_exceeded", "message": "Rate limit reached for requests"}},
                       {"Retry-After": "30"})
        elif "billing" in key:
            self._send(429, {"error": {"type": "insufficient_quota", "message": "You exceeded your current quota, please "
                                                                             "check your plan and billing details."}})
        elif "quota" in key:
            self._send(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                       "message": "Quota exceeded for metric: requests per day"}})
        elif "invalid" in key or not key:
            self._send(401, {"error": {"type": "invalid_api_key", "message": "Incorrect API key provided"}})
        elif "down" in key:
            self._send(503, {"error": {"message": "The service is temporarily unavailable"}})
        elif "slow" in key:
            time.sleep(5)
            return False
        else:
            return False
        return True

    def do_GET(self):
        if self.path.startswith("/_calls"):
            return self._send(200, CALLS)
        key = self._key()
        if self._fault(key):
            return
        if self.path.startswith("/gemini"):
            return self._send(200, {"models": [{"name": f"models/{m}", "supportedGenerationMethods": ["generateContent"]}
                                               for m in MODELS if m.startswith("gemini")]})
        if self.path.startswith("/anthropic"):
            return self._send(200, {"data": [{"id": m} for m in MODELS if m.startswith("claude")]})
        return self._send(200, {"data": [{"id": m} for m in MODELS]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        key = self._key()
        if self._fault(key):
            return
        model = body.get("model") or (self.path.split("/models/")[-1].split(":")[0] if "/models/" in self.path else "")
        if model == "retired-model":
            return self._send(404, {"error": {"message": f"The model `{model}` does not exist or you do not have access"}})
        texts = _texts(body)
        task = next((m.group(1) for t in texts for m in [re.search(r"\[\[AQ-TASK:([\w-]+)\]\]", t)] if m), None)
        if "garbage" in key.lower():
            answer = "this is not json"
        elif task:
            answer = json.dumps(_scripted(task, texts, key.lower()))
        else:
            answer = json.dumps({"ok": True, "served_by": key[-6:], "model": model})
        if self.path.startswith("/gemini"):
            return self._send(200, {"candidates": [{"content": {"parts": [{"text": answer}]}}]})
        if self.path.startswith("/anthropic"):
            # the shape of a real Messages response, so the official SDK parses it
            return self._send(200, {"id": "msg_mock", "type": "message", "role": "assistant", "model": model,
                                    "content": [{"type": "text", "text": answer}], "stop_reason": "end_turn",
                                    "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})
        return self._send(200, {"choices": [{"message": {"role": "assistant", "content": answer}}]})


def _texts(obj) -> list[str]:
    out: list[str] = []
    if isinstance(obj, str):
        if not obj.startswith("data:image") and len(obj) < 200_000:
            out.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in ("data", "inline_data", "images", "image_url"):
                out += _texts(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _texts(v)
    return out


STOP = set("a an the and or of to in on for with is are be by as at it its this that from your you can into then "
           "their them shows show page user users".split())


def _words(t: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if w not in STOP and len(w) > 1}


def _payload(texts: list[str]) -> dict:
    for t in texts:
        if "PAYLOAD:" in t:
            try:
                return json.loads(t.split("PAYLOAD:", 1)[1])
            except ValueError:
                pass
    return {}


def _scripted(task: str, texts: list[str], key: str) -> dict:
    """Word-overlap stand-in for AgentQA's tagged tasks (see the module docstring)."""
    p = _payload(texts)
    if task == "visual-act":
        want = _words(p.get("step", ""))
        done = " ".join(p.get("done_so_far") or []).lower()
        best, score = None, 0.0
        for c in p.get("controls") or []:
            name = " ".join(str(c.get(k) or "") for k in ("text", "label", "aria", "placeholder"))
            if not name.strip() or f"'{name.strip().lower()[:30]}" in done:
                continue
            sc = len(want & _words(name)) / max(1, len(_words(name)))
            if sc > score:
                best, score = c, sc
        if best is None or score < 0.5 or len(p.get("done_so_far") or []) >= 3:
            return {"done": True, "why": "nothing left on screen matches the step" if p.get("done_so_far") else
                    "the page already shows what the step needs"}
        return {"done": False, "why": "this control matches the step", "action": {"do": "click", "element": best["i"]}}
    if task == "visual-verify":
        want = _words(p.get("expected", ""))
        lines = [ln.strip() for ln in re.split(r"[\n.]", p.get("text", "")) if ln.strip()]
        best = max(lines, key=lambda ln: len(want & _words(ln)), default="")
        hit = len(want & _words(best)) / max(1, len(want))
        if "liar" in key:
            return {"verdict": "pass", "quote": "Your certificate has been issued and emailed", "why": "made up"}
        if hit >= 0.6:
            return {"verdict": "pass", "quote": best[:200], "why": "the page says so"}
        return {"verdict": "unsure", "quote": "", "why": "the page text does not mention it"}
    if task == "req-writer":
        items = []
        for r in p.get("requirements") or []:
            text = re.sub(r"\s+", " ", r.get("text") or "").strip().rstrip(".")
            actor = ((r.get("actors") or ["user"])[0] or "user").capitalize()
            statement = text if re.search(r"\b(shall|must|should|will|can)\b", text, re.I) else f"The system shall {text[:1].lower() + text[1:]}"
            if "liar" in key:
                statement += " within 30 seconds"
            items.append({"id": r.get("id"), "statement": statement + ".",
                          "user_story": f"As a {actor.lower()}, I want this to work as stated, so that my task is done.",
                          "steps": [{"actor": actor, "action": x} for x in (r.get("main_flow") or [])]
                                   + [{"actor": "System", "action": r.get("expected_outcome") or statement}],
                          "acceptance_criteria": [f"Given a {actor.lower()}, when the steps are followed, then {statement[:1].lower() + statement[1:]}"],
                          "open_points": [f"'{w}' needs a precise value" for w in r.get("vague_words") or []]})
        return {"items": items}
    if task == "casegen":
        cases = []
        for r in p.get("requirements") or []:
            flow = [x for x in r.get("main_flow") or [] if not x.lower().startswith("log in")]
            cases.append({"req_id": r.get("id"), "title": r.get("title") or r.get("id"), "scenario": "Positive",
                          "test_type": r.get("test_type") or "Positive", "priority": "Medium", "role": (r.get("actors") or [""])[0],
                          "objective": r.get("objective") or "", "test_data": "",
                          "steps": [{"action": "intent", "text": x} for x in flow[:5]] +
                                   [{"action": "verify", "expect": r.get("expected_outcome") or r.get("text") or ""}],
                          "expected": r.get("expected_outcome") or ""})
        return {"cases": cases}
    return {"ok": True}


def serve(port: int = 8950) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8950
    print(f"Mock AI providers on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
