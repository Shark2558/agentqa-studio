"""Small, comment-preserving edits to project.yaml (used by the Healer and the pilot check).

PyYAML would drop comments if it rewrote the file, so these helpers change only the lines
they must, then re-read the file to prove the change landed; on any doubt nothing is written.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml


def _workflow_span(lines: list[str], wf_id: str) -> tuple[int, int] | None:
    top = next((i for i, ln in enumerate(lines) if re.match(r"^workflows\s*:", ln)), None)
    if top is None:
        return None
    end_top = next((i for i in range(top + 1, len(lines)) if re.match(r"^[A-Za-z_]", lines[i])), len(lines))
    start = None
    indent = None
    for i in range(top + 1, end_top):
        m = re.match(r"^(\s*)-\s+id\s*:\s*['\"]?([^'\"#\s]+)", lines[i])
        if m:
            if start is not None and len(m.group(1)) == indent:
                return start, i
            if m.group(2) == wf_id:
                start, indent = i, len(m.group(1))
    return (start, end_top) if start is not None else None


def _find_workflow(cfg: dict, wf_id: str) -> dict | None:
    return next((w for w in cfg.get("workflows") or [] if str(w.get("id")) == wf_id), None)


def replace_in_workflow(path: Path, wf_id: str, old: str, new: str) -> bool:
    """Replace the value `old` with `new` inside one workflow; True when it changed."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    span = _workflow_span(lines, wf_id)
    if not span:
        return False
    a, b = span
    block = "".join(lines[a:b])
    changed = None
    for q in ('"', "'", ""):
        needle = f"{q}{old}{q}"
        if needle and needle in block:
            rep = f'"{new}"' if q == "" and re.search(r"[{}:#]", new) else f"{q}{new}{q}"
            changed = block.replace(needle, rep, 1)
            break
    if changed is None:
        return False
    out = "".join(lines[:a]) + changed + "".join(lines[b:])
    return _commit(path, out, lambda cfg: _contains(_find_workflow(cfg, wf_id), new))


def rename_fill_key(path: Path, wf_id: str | None, old_key: str, new_key: str) -> bool:
    """Rename a field in a workflow's fill: block (a renamed form field)."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    spans = [_workflow_span(lines, wf_id)] if wf_id else []
    if not wf_id:
        cfg = yaml.safe_load(text) or {}
        spans = [_workflow_span(lines, str(w.get("id"))) for w in cfg.get("workflows") or []]
    out = text
    did = False
    for span in sorted([s for s in spans if s], reverse=True):
        a, b = span
        block = "".join(lines[a:b])
        new_block = re.sub(rf"(?<=[{{,\s]){re.escape(old_key)}(?=\s*:)", new_key, block)
        if new_block != block:
            lines[a:b] = [new_block]
            did = True
    if not did:
        return False
    out = "".join(lines)
    return _commit(path, out, lambda cfg: any(_contains_key(w, new_key) for w in cfg.get("workflows") or []))


def replace_top_block(path: Path, key: str, new_block: str) -> None:
    """Replace a whole top-level section (e.g. `login:`) with new YAML text, or append it."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(key)}\s*:", ln)), None)
    block = new_block.rstrip("\n") + "\n"
    if start is None:
        out = text.rstrip("\n") + "\n\n" + block
    else:
        end = next((i for i in range(start + 1, len(lines)) if re.match(r"^[A-Za-z_#]", lines[i])), len(lines))
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        out = "".join(lines[:start]) + block + "".join(lines[end:])
    wanted = yaml.safe_load(new_block)[key]
    if not _commit(path, out, lambda cfg: cfg.get(key) == wanted):
        raise ValueError(f"could not update '{key}' in {path}")


def remove_top_block(path: Path, key: str) -> bool:
    """Remove a whole top-level section (e.g. `llm:`) and the blank lines after it; True when something was removed.
    Nothing is written unless the file still parses and the key is gone."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(key)}\s*:", ln)), None)
    if start is None:
        return False
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^[A-Za-z_#]", lines[i])), len(lines))
    out = "".join(lines[:start]) + "".join(lines[end:])
    return _commit(path, out, lambda cfg: key not in cfg)


def _contains(obj, value: str) -> bool:
    if isinstance(obj, dict):
        return any(_contains(v, value) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains(v, value) for v in obj)
    return obj == value


def _contains_key(obj, key: str) -> bool:
    if isinstance(obj, dict):
        return key in obj or any(_contains_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_key(v, key) for v in obj)
    return False


def _commit(path: Path, text: str, check) -> bool:
    try:
        cfg = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return False
    if not check(cfg):
        return False
    Path(path).write_text(text, encoding="utf-8")
    return True
