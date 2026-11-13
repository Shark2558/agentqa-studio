"""Content fingerprints (a hash that only tells 'did this change') say so: bandit's B324 rates a plain md5/sha1 call as
high severity, and the CI security job (`bandit -ll`) fails on it. This runs the same rule here, in a second, instead of
on GitHub ten minutes after a push."""
import ast
from pathlib import Path

from agentqa.agents.req_writer import _src_hash

PACKAGE = Path(__file__).resolve().parent.parent / "agentqa"
WEAK = {"md5", "sha1"}


def _unmarked_calls(path: Path) -> list[int]:
    """Line numbers of hashlib.md5(...) / hashlib.sha1(...) calls without usedforsecurity=False."""
    lines = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        is_weak = (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in WEAK
                   and isinstance(node.func.value, ast.Name) and node.func.value.id == "hashlib")
        if not is_weak:
            continue
        marked = any(k.arg == "usedforsecurity" and isinstance(k.value, ast.Constant) and k.value.value is False
                     for k in node.keywords)
        if not marked:
            lines.append(node.lineno)
    return lines


def test_every_md5_or_sha1_call_says_it_is_not_for_security():
    offenders = [f"{p.relative_to(PACKAGE.parent)}:{n}" for p in sorted(PACKAGE.rglob("*.py")) for n in _unmarked_calls(p)]
    assert offenders == []


def test_the_source_fingerprint_is_unchanged():
    # the first 12 hex digits of sha1: stored with earlier runs, so the value must not move
    assert _src_hash("abc") == "a9993e364706"
    assert _src_hash("") == _src_hash(None) == "da39a3ee5e6b"
