"""Small, comment-preserving edits to project.yaml (used by the Healer and the pilot check).

PyYAML would drop comments if it rewrote the file, so these helpers change only the lines
they must, then re-read the file to prove the change landed; on any doubt nothing is written.

A Healer's new value or field name comes from the application under test (M1.4 Phase C), so it is written as a
double-quoted scalar, and the workflow edits are kept only when the file, read back, differs from before in exactly the
intended place.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import yaml

# What YAML may not hold as it is inside quotes (PyYAML's reader refuses it, or reads it as a line break, or as a
# byte-order mark): written as \uXXXX instead.
_UNPRINTABLE = re.compile("[\x85\u2028\u2029\uFEFF]|[^\x09\x0A\x0D\x20-\x7E\xA0-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")
_PLAIN_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


def quoted(value: str) -> str:
    """`value` as a YAML double-quoted scalar: JSON's escapes, plus \\uXXXX for what YAML may not hold as it is."""
    return _UNPRINTABLE.sub(lambda m: f"\\u{ord(m.group()):04x}", json.dumps(value, ensure_ascii=False))


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


def replace_in_workflow(path: Path, wf_id: str, old: str, new: str, *, step: int | None = None,
                        key: str | None = None) -> bool:
    """Replace the value `old` with `new` inside one workflow (in its `step`, 1-based, under `key`, when given); True
    when it changed. Each place the old text appears is tried in turn; nothing is written unless the file, read back,
    differs from before in exactly one value, the intended one, which went from `old` to `new`."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    span = _workflow_span(lines, wf_id)
    before = _parsed(text)
    if not span or before is None:
        return False
    a, b = span
    for changed in _candidates("".join(lines[a:b]), old, new):
        out = "".join(lines[:a]) + changed + "".join(lines[b:])
        if _commit(path, out, lambda cfg: _one_value_changed(before, cfg, wf_id, old, new, step, key)):
            return True
    return False


def _candidates(block: str, old: str, new: str):
    """`block` with one place where `old` appears (quoted either way, or bare) replaced by `new`, quoted."""
    for q in ('"', "'", ""):
        needle = f"{q}{old}{q}"
        at = block.find(needle) if needle else -1
        while at != -1:
            yield block[:at] + quoted(new) + block[at + len(needle):]
            at = block.find(needle, at + 1)


def rename_fill_key(path: Path, wf_id: str | None, old_key: str, new_key: str) -> bool:
    """Rename a field in a workflow's fill: block (a renamed form field). Nothing is written unless the file, read
    back, is the old one with exactly that key renamed in those workflows' fill blocks."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    before = _parsed(text)
    if before is None:
        return False
    ids = [wf_id] if wf_id else [str(w.get("id")) for w in before.get("workflows") or [] if isinstance(w, dict)]
    key = new_key if _PLAIN_KEY.fullmatch(new_key) else quoted(new_key)
    did = False
    for span in sorted([s for s in (_workflow_span(lines, i) for i in ids) if s], reverse=True):
        a, b = span
        block = "".join(lines[a:b])
        new_block = re.sub(rf"(?<=[{{,\s]){re.escape(old_key)}(?=\s*:)", lambda _m: key, block)
        if new_block != block:
            lines[a:b] = [new_block]
            did = True
    wanted = _renamed(before, ids, old_key, new_key)
    if not did or wanted is None:
        return False
    return _commit(path, "".join(lines), lambda cfg: cfg == wanted)


def _parsed(text: str) -> dict | None:
    try:
        cfg = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return None
    return cfg if isinstance(cfg, dict) else None


def _differences(a, b, at: tuple = ()) -> list[tuple]:
    """Where two parsed documents differ: the paths to differing values (a changed shape counts at its parent)."""
    if isinstance(a, dict) and isinstance(b, dict):
        if list(a) != list(b):
            return [at]
        return [d for k in a for d in _differences(a[k], b[k], at + (k,))]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [at]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _differences(x, y, at + (i,))]
    return [] if type(a) is type(b) and a == b else [at]


def _value(doc, at: tuple):
    for step in at:
        doc = doc[step]
    return doc


def _one_value_changed(before: dict, after: dict, wf_id: str, old: str, new: str, step: int | None = None,
                       key: str | None = None) -> bool:
    found = _differences(before, after)
    if len(found) != 1 or len(found[0]) < 3 or found[0][0] != "workflows":
        return False
    at = found[0]
    workflow = before["workflows"][at[1]]
    in_place = step is None or at[2:] == ("steps", step - 1, key)
    return isinstance(workflow, dict) and str(workflow.get("id")) == wf_id and in_place \
        and _value(before, at) == old and _value(after, at) == new


def _renamed(before: dict, ids: list[str], old_key: str, new_key: str) -> dict | None:
    """`before` with `old_key` renamed to `new_key` in the fill blocks of the named workflows; None when a block
    already has `new_key` (renaming onto it would lose that value)."""
    out = copy.deepcopy(before)
    for w in out.get("workflows") or []:
        if not isinstance(w, dict) or str(w.get("id")) not in ids:
            continue
        for step in w.get("steps") or []:
            fill = step.get("fill") if isinstance(step, dict) else None
            if isinstance(fill, dict) and old_key in fill:
                if new_key in fill and new_key != old_key:
                    return None
                step["fill"] = {(new_key if k == old_key else k): v for k, v in fill.items()}
    return out


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


def _commit(path: Path, text: str, check) -> bool:
    try:
        cfg = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return False
    if not check(cfg):
        return False
    Path(path).write_text(text, encoding="utf-8")
    return True
