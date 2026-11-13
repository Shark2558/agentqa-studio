"""Turns a pytest JUnit file into GitHub '::error' notes. A failed job's log needs a sign-in, but the notes a job prints
this way show on the run page and in the public API, so the failed tests are named where anyone can read them.

    python tools/ci_annotate.py unit-junit.xml
"""
from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_NOTES = 12      # more than a person reads; the rest are counted
MAX_TEXT = 600


def _escape(text: str) -> str:
    """The data part of a workflow command: a % or a line break would end the note early."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    return _escape(text).replace(":", "%3A").replace(",", "%2C")


def _problems(root: ET.Element) -> Iterator[tuple[str, str]]:
    for case in root.iter("testcase"):
        problem = next((e for e in (case.find("failure"), case.find("error")) if e is not None), None)
        if problem is not None:
            yield f"{case.get('classname', '')}::{case.get('name', '')}", (problem.get("message") or problem.text or "").strip()


def notes(junit_xml: str) -> list[str]:
    """One '::error' line per failed or errored test (the first MAX_NOTES), then a count of the rest."""
    found = list(_problems(ET.fromstring(junit_xml)))
    if not found:
        return ["::error title=pytest::no failed test in the JUnit file: the run stopped before the tests finished"]
    lines = [f"::error title={_escape_property(name)}::{_escape(text[:MAX_TEXT])}" for name, text in found[:MAX_NOTES]]
    if len(found) > MAX_NOTES:
        lines.append(f"::error title=pytest::and {len(found) - MAX_NOTES} more failed tests")
    return lines


def notes_for_file(path: Path) -> list[str]:
    if not path.exists():
        return [f"::error title=pytest::no JUnit file at {_escape(str(path))}: pytest stopped before it could write one"]
    try:
        return notes(path.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        return [f"::error title=pytest::the JUnit file could not be read: {_escape(str(exc))}"]


def main(argv: list[str]) -> int:
    for line in notes_for_file(Path(argv[1] if len(argv) > 1 else "unit-junit.xml")):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
