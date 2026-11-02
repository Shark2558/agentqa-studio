"""The design-token contrast checker (frontend/design-system/check_contrast.py) is the build's accessibility gate, so
its maths and its CSS parsing get tests of their own."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

CHECKER = Path(__file__).resolve().parents[2] / "frontend" / "design-system" / "check_contrast.py"
spec = importlib.util.spec_from_file_location("check_contrast", CHECKER)
cc = importlib.util.module_from_spec(spec)
sys.modules["check_contrast"] = cc
spec.loader.exec_module(cc)


@pytest.mark.parametrize("fg, bg, expected", [
    ("#ffffff", "#000000", 21.0),        # the WCAG maximum
    ("#767676", "#ffffff", 4.54),        # the classic "just passes AA" grey
    ("#2563eb", "#ffffff", 5.17),        # brand blue on white
])
def test_ratio_matches_the_wcag_reference_values(fg, bg, expected):
    assert cc.ratio(fg, bg) == pytest.approx(expected, abs=0.01)


def test_light_dark_values_split_into_the_two_themes():
    css = ":root { --color-bg: light-dark(#ffffff, #000000); --color-ink: #123456; }"
    themes = cc.parse_tokens(css)
    assert themes["light"]["--color-bg"] == "#ffffff" and themes["dark"]["--color-bg"] == "#000000"
    assert themes["light"]["--color-ink"] == "#123456" and themes["dark"]["--color-ink"] == "#123456"


def test_var_chains_resolve_and_comments_are_ignored():
    css = "/* :root { --color-ink: #000000; } */\n:root { --blue: #2563eb; --color-primary: var(--blue); --x: var( --color-primary ); }"
    tokens = cc.parse_tokens(css)["light"]
    assert cc.resolve(tokens, "--x") == "#2563eb"


def test_media_blocks_never_leak_into_the_root_tokens():
    css = ":root { --color-ink: #000000; }\n@media (prefers-reduced-motion: reduce) { :root { --color-ink: #ffffff; } }"
    assert cc.parse_tokens(css)["light"]["--color-ink"] == "#000000"


def test_non_opaque_values_fail_closed_with_a_clear_message():
    tokens = {"--color-x": "rgba(0, 0, 0, 0.5)"}
    with pytest.raises(ValueError, match="opaque"):
        cc.resolve(tokens, "--color-x")


def test_a_failing_pair_is_reported_and_fails_the_run():
    css = ":root { --color-ink: #999999; --color-bg: #ffffff; }"
    report, failures = cc.check(css, pairs=[("--color-ink", "--color-bg", 4.5, "grey on white")])
    assert len(failures) == 2 and "2.85:1 < 4.5:1" in failures[0]        # light and dark both fail
    assert any(line.startswith("  FAIL") for line in report)
