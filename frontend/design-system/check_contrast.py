"""WCAG contrast check for the AgentQA Studio design tokens — the build's accessibility gate (`make lint`).

    python frontend/design-system/check_contrast.py [frontend/design-system/tokens.css]

tokens.css declares every colour once in `:root`, with `light-dark(<light>, <dark>)` where the themes differ. This
script parses that block (top-level only; `@media` blocks are ignored), resolves `var()` references, and computes
the WCAG 2.x contrast ratio of every pair in PAIRS for both themes. Exit 1 when any pair is below its minimum
(4.5:1 for text, 3:1 for large text, icons, control boundaries and chart marks). Standard library only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TOKENS = HERE / "tokens.css"
TEXT_MIN = 4.5
NON_TEXT_MIN = 3.0
MAX_VAR_DEPTH = 10

# (foreground token, background token, minimum ratio, what it is) — every combination the screens actually use
PAIRS: list[tuple[str, str, float, str]] = [
    # text on surfaces
    ("--color-ink", "--color-bg", TEXT_MIN, "body text on page background"),
    ("--color-ink", "--color-surface", TEXT_MIN, "body text on card"),
    ("--color-ink", "--color-surface-raised", TEXT_MIN, "body text on raised card"),
    ("--color-ink", "--color-surface-2", TEXT_MIN, "body text on sunken panel / hovered row"),
    ("--color-ink-2", "--color-surface", TEXT_MIN, "secondary text on card"),
    ("--color-ink-2", "--color-bg", TEXT_MIN, "nav item text on page background"),
    ("--color-muted", "--color-surface", TEXT_MIN, "muted text on card"),
    ("--color-muted", "--color-surface-raised", TEXT_MIN, "muted text on raised card"),
    ("--color-muted", "--color-surface-2", TEXT_MIN, "table header text on sunken header"),
    ("--color-muted", "--color-bg", TEXT_MIN, "muted text on page background"),
    # brand
    ("--color-on-primary", "--color-primary", TEXT_MIN, "button label on primary"),
    ("--color-on-primary", "--color-primary-hover", TEXT_MIN, "button label on hovered primary"),
    ("--color-primary", "--color-surface", TEXT_MIN, "link / primary text on card"),
    ("--color-primary", "--color-bg", TEXT_MIN, "link on page background"),
    ("--color-primary-ink", "--color-primary-soft", TEXT_MIN, "primary text on primary tint"),
    ("--color-primary-ink", "--color-bg", TEXT_MIN, "current nav item on page background"),
    ("--color-primary-ink", "--color-surface-raised", TEXT_MIN, "selected switch label on raised thumb"),
    # status text on the surfaces it appears on (cards, sunken panels, hovered rows)
    *[(f"--color-{s}", bg, TEXT_MIN, f"{s} status text on {name}")
      for s in ("ok", "warn", "bad", "info", "visual")
      for bg, name in (("--color-surface", "card"), ("--color-surface-2", "sunken panel / hovered row"))],
    # badges: ink on tint
    *[(f"--color-{s}-ink", f"--color-{s}-soft", TEXT_MIN, f"{s} badge text on its tint")
      for s in ("ok", "warn", "bad", "info", "visual", "neutral")],
    # non-text: focus, boundaries, icons, chart marks
    ("--color-focus", "--color-surface", NON_TEXT_MIN, "focus ring on card"),
    ("--color-focus", "--color-bg", NON_TEXT_MIN, "focus ring on page background"),
    ("--color-line-strong", "--color-surface", NON_TEXT_MIN, "control boundary on card"),
    ("--color-icon", "--color-surface", NON_TEXT_MIN, "icon on card"),
    ("--color-icon", "--color-bg", NON_TEXT_MIN, "icon on page background"),
    ("--color-track", "--color-bg", NON_TEXT_MIN, "pending pipeline bar in a sunken well"),
    ("--color-primary", "--color-bad-soft", NON_TEXT_MIN, "bullet-chart bar over the 'not ready' band"),
]

_HEX = re.compile(r"^#([0-9a-fA-F]{6})$")
_DECL = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
_LIGHT_DARK = re.compile(r"^light-dark\(\s*([^,]+?)\s*,\s*(.+?)\s*\)$", re.S)
_VAR = re.compile(r"^var\(\s*(--[\w-]+)\s*\)$")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _top_level_root_blocks(css: str) -> list[str]:
    """Bodies of the `:root { … }` rules at nesting depth 0 (so nothing inside an @media block counts)."""
    bodies, depth, start, selector = [], 0, None, ""
    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                selector = css[:i].rsplit("}", 1)[-1].strip()
                start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and selector == ":root" and start is not None:
                bodies.append(css[start:i])
    return bodies


def parse_tokens(css: str) -> dict[str, dict[str, str]]:
    """{"light": {token: value}, "dark": {token: value}} from the top-level :root block(s); light-dark() is split."""
    themes: dict[str, dict[str, str]] = {"light": {}, "dark": {}}
    for body in _top_level_root_blocks(_strip_comments(css)):
        for name, raw in _DECL.findall(body):
            value = raw.strip()
            pair = _LIGHT_DARK.match(value)
            themes["light"][name] = pair.group(1) if pair else value
            themes["dark"][name] = pair.group(2) if pair else value
    return themes


def resolve(tokens: dict[str, str], name: str, depth: int = 0) -> str:
    value = tokens.get(name)
    if value is None:
        raise KeyError(f"{name} is not defined")
    ref = _VAR.match(value)
    if ref:
        if depth > MAX_VAR_DEPTH:
            raise ValueError(f"{name}: var() chain too deep")
        return resolve(tokens, ref.group(1), depth + 1)
    if not _HEX.match(value):
        raise ValueError(f"{name}: {value!r} is not an opaque 6-digit hex colour (contrast pairs must be opaque)")
    return value.lower()


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def ratio(fg: str, bg: str) -> float:
    lf, lb = luminance(fg), luminance(bg)
    return (max(lf, lb) + 0.05) / (min(lf, lb) + 0.05)


def check(css: str, pairs: list[tuple[str, str, float, str]] | None = None) -> tuple[list[str], list[str]]:
    """(report lines, failures) over both themes."""
    report, failures = [], []
    for theme, tokens in parse_tokens(css).items():
        report.append(f"[{theme}]")
        for fg, bg, minimum, what in (pairs or PAIRS):
            try:
                r = ratio(resolve(tokens, fg), resolve(tokens, bg))
            except (KeyError, ValueError) as exc:
                failures.append(f"{theme}: {what}: {exc}")
                report.append(f"  MISSING {what}: {exc}")
                continue
            if r < minimum:
                failures.append(f"{theme}: {what}: {r:.2f}:1 < {minimum}:1 ({fg} on {bg})")
            report.append(f"  {'FAIL' if r < minimum else 'ok  '} {r:5.2f}:1  (min {minimum})  {what}  {fg} on {bg}")
    return report, failures


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_TOKENS
    if not path.is_file():
        print(f"tokens file not found: {path}")
        return 1
    report, failures = check(path.read_text(encoding="utf-8"))
    print("\n".join(report))
    total = len(PAIRS) * 2
    print(f"\n{total - len(failures)} of {total} pairs pass")
    if failures:
        print("\nFAILURES:\n  " + "\n  ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
