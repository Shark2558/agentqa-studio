"""M1.2 slice 5: detecting a local model server. Only two fixed loopback addresses are ever contacted (Ollama on
11434, LM Studio on 1234), with a one-second timeout, and every outcome comes with a plain-English fix."""
from __future__ import annotations

import httpx
import pytest

from conftest import free_port

from agentqa.ai import local as L
from demo import mock_ai


@pytest.fixture
def stand_in(monkeypatch):
    port = free_port()
    srv = mock_ai.serve(port)
    base = f"http://127.0.0.1:{port}"
    monkeypatch.setattr(L, "PROBES", (("ollama", f"{base}/ollama/api/tags"), ("lmstudio", f"{base}/lmstudio/v1/models")))
    yield base
    srv.shutdown()
    srv.server_close()


def by_provider(rows: list[dict]) -> dict[str, dict]:
    return {r["provider"]: r for r in rows}


def test_the_fixed_addresses_are_loopback_only_and_the_timeout_is_one_second():
    assert [p for p, _ in L.PROBES] == ["ollama", "lmstudio"]
    assert all(url.startswith("http://127.0.0.1:") for _, url in L.PROBES)
    assert L.PROBES[0][1].endswith(":11434/api/tags") and L.PROBES[1][1].endswith(":1234/v1/models")
    assert L.TIMEOUT_S == 1.0


def test_running_with_models_offers_the_address_for_use_it(stand_in):
    rows = by_provider(L.probe())
    ol, lm = rows["ollama"], rows["lmstudio"]
    assert ol["running"] and ol["models"] == ["qwen3:4b"] and ol["fix"] is None and ol["name"] == "Ollama (local)"
    assert ol["base_url"] == f"{stand_in}/ollama" and ol["model"] == "qwen3:4b"
    assert lm["running"] and lm["models"] == ["qwen3:4b"] and lm["fix"] is None and lm["base_url"] == f"{stand_in}/lmstudio/v1"


def test_running_without_a_model_names_the_pull_command(stand_in, monkeypatch):
    monkeypatch.setattr(mock_ai, "LOCAL_MODELS", [])
    rows = by_provider(L.probe())
    assert rows["ollama"]["running"] and rows["ollama"]["models"] == [] and rows["ollama"]["model"] is None
    assert "ollama pull qwen3:4b" in rows["ollama"]["fix"]
    assert rows["lmstudio"]["running"] and "load" in rows["lmstudio"]["fix"].lower() and "LM Studio" in rows["lmstudio"]["fix"]


def test_nothing_listening_is_not_running_with_an_install_hint(monkeypatch):
    monkeypatch.setattr(L, "PROBES", (("ollama", "http://127.0.0.1:9/api/tags"), ("lmstudio", "http://127.0.0.1:9/v1/models")))
    rows = by_provider(L.probe())
    assert not rows["ollama"]["running"] and "https://ollama.com" in rows["ollama"]["fix"]
    assert not rows["lmstudio"]["running"] and "LM Studio" in rows["lmstudio"]["fix"] and rows["lmstudio"]["models"] == []


def test_only_the_two_fixed_endpoints_are_ever_contacted(monkeypatch):
    seen: list[str] = []

    def fake_get(url, timeout=None, **kw):
        seen.append(url)
        assert timeout == L.TIMEOUT_S
        raise httpx.ConnectError("closed")
    monkeypatch.setattr(httpx, "get", fake_get)
    L.probe()
    assert seen == [url for _, url in L.PROBES]
    with pytest.raises(TypeError):
        L.probe("http://10.0.0.5:11434")          # no address parameter: the owner cannot point it elsewhere


def test_a_garbage_answer_counts_as_not_running(monkeypatch):
    class R:
        status_code = 200
        text = "<html>not json</html>"

        def json(self):
            raise ValueError("not json")
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None, **kw: R())
    rows = by_provider(L.probe())
    assert not rows["ollama"]["running"] and rows["ollama"]["fix"]
