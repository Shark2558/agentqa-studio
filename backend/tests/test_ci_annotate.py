"""CI helper: a failed GitHub job's log needs a sign-in, but the notes a job prints as '::error ...' lines show on the run
page and in the public API. tools/ci_annotate.py turns a pytest JUnit file into those notes, so the failed tests are named
where anyone can read them."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ci_annotate as tool  # noqa: E402

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4" failures="1" errors="1">
  <testcase classname="tests.test_a" name="test_fine" time="0.1"/>
  <testcase classname="tests.test_a" name="test_breaks[3.12]" time="0.2">
    <failure message="assert 1 == 2&#10;where 1 = f()">traceback text</failure>
  </testcase>
  <testcase classname="tests.test_b" name="test_setup_fails" time="0.0">
    <error message="fixture 'gw' not found: 100% sure">setup text</error>
  </testcase>
  <testcase classname="tests.test_b" name="test_skipped"><skipped message="not on Windows"/></testcase>
</testsuite></testsuites>"""


def test_names_each_failed_and_errored_test_and_skips_the_rest():
    notes = tool.notes(JUNIT)
    assert len(notes) == 2
    assert notes[0].startswith("::error title=tests.test_a%3A%3Atest_breaks[3.12]::assert 1 == 2%0Awhere 1 = f()")
    assert notes[1].startswith("::error title=tests.test_b%3A%3Atest_setup_fails::fixture 'gw' not found: 100%25 sure")


def test_a_note_is_one_line_and_never_too_long():
    long = JUNIT.replace("assert 1 == 2&#10;where 1 = f()", "x" * 5000)
    note = tool.notes(long)[0]
    assert "\n" not in note and len(note) < tool.MAX_TEXT + 200


def test_many_failures_are_cut_with_a_count():
    cases = "".join(f'<testcase classname="t" name="n{i}"><failure message="m"/></testcase>' for i in range(20))
    notes = tool.notes(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
    assert len(notes) == tool.MAX_NOTES + 1
    assert notes[-1] == f"::error title=pytest::and {20 - tool.MAX_NOTES} more failed tests"


def test_no_failure_in_the_file_says_the_run_stopped_early():
    notes = tool.notes('<testsuites><testsuite><testcase classname="t" name="ok"/></testsuite></testsuites>')
    assert len(notes) == 1 and "stopped before the tests finished" in notes[0]


def test_the_end_of_a_log_becomes_one_note():
    log = "\n".join(f"line {i}" for i in range(100)) + "\n\n"
    assert tool.tail_note(log, lines=3) == "::error title=last lines of the log::line 97%0Aline 98%0Aline 99"


def test_a_log_note_cuts_long_lines_and_escapes_percent_signs():
    note = tool.tail_note("x" * 1000 + "\n50% done", width=20)
    assert note == "::error title=last lines of the log::" + "x" * 20 + "%0A50%25 done"


def test_a_missing_log_is_reported_not_raised(tmp_path):
    assert "no log file" in tool.tail_for_file(tmp_path / "nope.log")


def test_a_missing_or_broken_file_is_reported_not_raised(tmp_path):
    assert "no JUnit file" in tool.notes_for_file(tmp_path / "nope.xml")[0]
    broken = tmp_path / "broken.xml"
    broken.write_text("<testsuites><oops", encoding="utf-8")
    assert "could not be read" in tool.notes_for_file(broken)[0]
