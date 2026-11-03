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
    report, failures = cc.check(css, pairs=[("--color-ink", "--color-bg", 4.5, "grey on white")], accents=("blue",))
    assert len(failures) == 2 and "2.85:1 < 4.5:1" in failures[0]        # light and dark both fail
    assert any(line.startswith("  FAIL") for line in report)


# ---- accents (M1.2-UI): `:root[data-accent="x"]` blocks override the brand tokens per accent -------------------------

ACCENT_CSS = """
:root { --white: #ffffff; --blue-600: #2563eb; --teal-700: #0f766e;
        --color-bg: light-dark(#f8fafc, #0f172a); --color-ink: light-dark(#1e293b, #e2e8f0);
        --accent: light-dark(var(--blue-600), #60a5fa); --color-primary: var(--accent); --color-on-primary: light-dark(#ffffff, #0b1120); }
:root[data-accent="teal"] { --accent: light-dark(var(--teal-700), #2dd4bf); }
@media (prefers-reduced-motion: reduce) { :root[data-accent="teal"] { --accent: #000000; } }
"""


def test_accent_blocks_are_parsed_and_media_ones_ignored():
    accents = cc.parse_accents(ACCENT_CSS)
    assert accents["teal"]["light"]["--accent"] == "var(--teal-700)"
    assert accents["teal"]["dark"]["--accent"] == "#2dd4bf"          # the @media override never leaks in
    assert "blue" not in accents                                       # blue has no block: it IS the :root default


def test_an_accent_override_changes_only_that_accent():
    pairs = [("--color-on-primary", "--color-primary", 4.5, "button label on primary")]
    report, failures = cc.check(ACCENT_CSS, pairs=pairs, accents=("blue", "teal"))
    assert not failures
    blue, teal = f"{cc.ratio('#2563eb', '#ffffff'):.2f}", f"{cc.ratio('#0f766e', '#ffffff'):.2f}"
    assert any("light/blue" in line and blue in line for line in report)   # #2563eb stays for blue
    assert any("light/teal" in line and teal in line for line in report)   # #0f766e for teal


def test_a_pair_failing_in_one_theme_and_accent_names_both():
    css = ACCENT_CSS.replace("#2dd4bf", "#134e4a")                      # dark teal becomes too dark for night text
    pairs = [("--color-on-primary", "--color-primary", 4.5, "button label on primary")]
    _, failures = cc.check(css, pairs=pairs, accents=("blue", "teal"))
    assert len(failures) == 1 and failures[0].startswith("dark/teal: button label on primary:")


def test_a_missing_accent_block_fails_closed():
    _, failures = cc.check(ACCENT_CSS, pairs=[], accents=("blue", "teal", "green"))
    assert failures == ['green: no :root[data-accent="green"] block in tokens.css']


def test_accent_free_pairs_are_checked_once_per_theme_and_accent_pairs_per_accent():
    pairs = [("--color-ink", "--color-bg", 4.5, "body text"),                     # touches no accent token
             ("--color-on-primary", "--color-primary", 4.5, "button label")]      # resolves through --accent
    plan = cc.plan_checks(ACCENT_CSS, pairs=pairs, accents=("blue", "teal"))
    assert len(plan) == 1 * 2 + 1 * 2 * 2                                         # base once per theme; accent pair per theme per accent
    assert cc.count_checks(cc.PAIRS, accent_pairs=14, accents=cc.ACCENTS) == 31 * 2 + 14 * 2 * 5 == 202


def test_the_shipped_tokens_pass_for_every_theme_and_accent():
    css = cc.DEFAULT_TOKENS.read_text(encoding="utf-8")
    _, failures = cc.check(css)                                            # default pairs and accents
    assert failures == []
    assert set(cc.ACCENTS) == {"blue", "indigo", "teal", "green", "slate"}
    assert all(a == "blue" or a in cc.parse_accents(css) for a in cc.ACCENTS)
