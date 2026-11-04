"""WCAG contrast check for the AgentQA Studio design tokens — the build's accessibility gate (`make lint`).

    python frontend/design-system/check_contrast.py [frontend/design-system/tokens.css]

tokens.css declares every colour once in `:root`, with `light-dark(<light>, <dark>)` where the themes differ, and
overrides the brand slots per accent in `:root[data-accent="<name>"]` blocks. This script parses those top-level
blocks (`@media` blocks are ignored), resolves `var()` references, and computes the WCAG 2.x contrast ratio of every
pair in PAIRS: once per theme for pairs that never touch an accent token, and once per theme per accent for the rest.
Exit 1 when any pair is below its minimum (4.5:1 for text, 3:1 for large text, icons, control boundaries and chart
marks) or when an accent has no block. Standard library only.
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
THEMES = ("light", "dark")
ACCENTS = ("blue", "indigo", "teal", "green", "slate")
DEFAULT_ACCENT = ACCENTS[0]          # the :root values ARE this accent; it needs no block of its own

Pair = tuple[str, str, float, str]
Check = tuple[str, str | None, Pair]

# (foreground token, background token, minimum ratio, what it is) — every combination the screens actually use
PAIRS: list[Pair] = [
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
    # brand (these resolve through the accent slots, so they are checked per accent)
    ("--color-on-primary", "--color-primary", TEXT_MIN, "button label on primary"),
    ("--color-on-primary", "--color-primary-hover", TEXT_MIN, "button label on hovered primary"),
    ("--color-primary", "--color-surface", TEXT_MIN, "link / primary text on card"),
    ("--color-primary", "--color-bg", TEXT_MIN, "link on page background"),
    ("--color-primary-ink", "--color-primary-soft", TEXT_MIN, "primary text on primary tint"),
    ("--color-primary-ink", "--color-bg", TEXT_MIN, "current nav item on page background"),
    ("--color-primary-ink", "--color-surface", TEXT_MIN, "current nav item on card / drawer"),
    ("--color-primary-ink", "--color-surface-2", TEXT_MIN, "link on hovered row"),
    ("--color-primary-ink", "--color-surface-raised", TEXT_MIN, "selected switch label on raised thumb"),
    ("--color-ink-2", "--color-primary-soft", TEXT_MIN, "selected choice description on the accent tint"),
    # status text on the surfaces it appears on (cards, sunken panels, hovered rows)
    *[(f"--color-{s}", bg, TEXT_MIN, f"{s} status text on {name}")
      for s in ("ok", "warn", "bad", "info", "visual")
      for bg, name in (("--color-surface", "card"), ("--color-surface-2", "sunken panel / hovered row"))],
    # badges: ink on tint
    *[(f"--color-{s}-ink", f"--color-{s}-soft", TEXT_MIN, f"{s} badge text on its tint")
      for s in ("ok", "warn", "bad", "info", "visual", "neutral")],
    # Live View (M1.3): event labels and verdicts in status ink on cards and sunken frames; ids and headings on sunken panels
    *[(f"--color-{s}-ink", bg, TEXT_MIN, f"{s} ink text on {name}")
      for s in ("ok", "warn", "bad", "info")
      for bg, name in (("--color-surface", "card"), ("--color-surface-2", "sunken panel"))],
    ("--color-ink-2", "--color-surface-2", TEXT_MIN, "pipeline heading / requirement id on a sunken panel"),
    # non-text: focus, boundaries, icons, chart marks
    ("--color-focus", "--color-surface", NON_TEXT_MIN, "focus ring on card"),
    ("--color-focus", "--color-bg", NON_TEXT_MIN, "focus ring on page background"),
    ("--color-focus", "--color-surface-raised", NON_TEXT_MIN, "focus ring on menu / overlay"),
    ("--color-line-strong", "--color-surface", NON_TEXT_MIN, "control boundary on card"),
    ("--color-line-strong", "--color-bg", NON_TEXT_MIN, "control boundary on page background"),
    ("--color-icon", "--color-surface", NON_TEXT_MIN, "icon on card"),
    ("--color-icon", "--color-bg", NON_TEXT_MIN, "icon on page background"),
    ("--color-icon", "--color-surface-2", NON_TEXT_MIN, "icon on a test tile that has not run (Live View)"),
    ("--color-track", "--color-bg", NON_TEXT_MIN, "pending pipeline bar in a sunken well"),
    ("--color-primary", "--color-bad-soft", NON_TEXT_MIN, "bullet-chart bar over the 'not ready' band"),
    ("--color-primary", "--color-primary-soft", NON_TEXT_MIN, "selected accent swatch ring on its tint"),
    # M1.4 gates: a selected case row is tinted; the "why?" panel is raised
    ("--color-ink", "--color-primary-soft", TEXT_MIN, "case id and title in a selected row (M1.4)"),
    ("--color-line-strong", "--color-surface-raised", NON_TEXT_MIN, "reason box boundary on the raised why panel (M1.4)"),
]

_HEX = re.compile(r"^#([0-9a-fA-F]{6})$")
_DECL = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
_LIGHT_DARK = re.compile(r"^light-dark\(\s*([^,]+?)\s*,\s*(.+?)\s*\)$", re.S)
_VAR = re.compile(r"^var\(\s*(--[\w-]+)\s*\)$")
_ACCENT_SELECTOR = re.compile(r'^:root\[data-accent="([\w-]+)"\]$')


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _top_level_blocks(css: str) -> list[tuple[str, str]]:
    """(selector, body) of every rule at nesting depth 0 (so nothing inside an @media block counts)."""
    blocks, depth, start, selector = [], 0, None, ""
    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                selector = css[:i].rsplit("}", 1)[-1].strip()
                start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                blocks.append((selector, css[start:i]))
    return blocks


def _split_themes(body: str, into: dict[str, dict[str, str]]) -> None:
    for name, raw in _DECL.findall(body):
        value = raw.strip()
        pair = _LIGHT_DARK.match(value)
        into["light"][name] = pair.group(1) if pair else value
        into["dark"][name] = pair.group(2) if pair else value


def parse_tokens(css: str) -> dict[str, dict[str, str]]:
    """{"light": {token: value}, "dark": {token: value}} from the top-level :root block(s); light-dark() is split."""
    themes: dict[str, dict[str, str]] = {"light": {}, "dark": {}}
    for selector, body in _top_level_blocks(_strip_comments(css)):
        if selector == ":root":
            _split_themes(body, themes)
    return themes


def parse_accents(css: str) -> dict[str, dict[str, dict[str, str]]]:
    """{accent: {"light": {...}, "dark": {...}}} from the top-level `:root[data-accent="…"]` blocks."""
    accents: dict[str, dict[str, dict[str, str]]] = {}
    for selector, body in _top_level_blocks(_strip_comments(css)):
        m = _ACCENT_SELECTOR.match(selector)
        if m:
            _split_themes(body, accents.setdefault(m.group(1), {"light": {}, "dark": {}}))
    return accents


def resolve_chain(tokens: dict[str, str], name: str) -> tuple[str, set[str]]:
    """(opaque hex value, every token name visited on the way)."""
    seen: set[str] = set()
    for _ in range(MAX_VAR_DEPTH + 1):
        seen.add(name)
        value = tokens.get(name)
        if value is None:
            raise KeyError(f"{name} is not defined")
        ref = _VAR.match(value)
        if not ref:
            if not _HEX.match(value):
                raise ValueError(f"{name}: {value!r} is not an opaque 6-digit hex colour (contrast pairs must be opaque)")
            return value.lower(), seen
        name = ref.group(1)
    raise ValueError(f"{name}: var() chain too deep")


def resolve(tokens: dict[str, str], name: str) -> str:
    return resolve_chain(tokens, name)[0]


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def ratio(fg: str, bg: str) -> float:
    lf, lb = luminance(fg), luminance(bg)
    return (max(lf, lb) + 0.05) / (min(lf, lb) + 0.05)


def _touches(tokens: dict[str, str], name: str, overridden: set[str]) -> bool:
    try:
        return bool(resolve_chain(tokens, name)[1] & overridden)
    except (KeyError, ValueError):
        return True                      # unresolvable: check it everywhere so the failure is reported


def plan_checks(css: str, pairs: list[Pair] | None = None, accents: tuple[str, ...] | None = None) -> list[Check]:
    """Every (theme, accent-or-None, pair) to measure: accent-free pairs once per theme, the rest once per accent."""
    base, blocks = parse_tokens(css), parse_accents(css)
    overridden = {n for b in blocks.values() for th in b.values() for n in th}
    plan: list[Check] = []
    for theme in THEMES:
        for pair in (pairs if pairs is not None else PAIRS):
            if _touches(base[theme], pair[0], overridden) or _touches(base[theme], pair[1], overridden):
                plan.extend((theme, a, pair) for a in (accents or ACCENTS))
            else:
                plan.append((theme, None, pair))
    return plan


def count_checks(pairs: list[Pair], accent_pairs: int, accents: tuple[str, ...]) -> int:
    return (len(pairs) - accent_pairs) * len(THEMES) + accent_pairs * len(THEMES) * len(accents)


def check(css: str, pairs: list[Pair] | None = None, accents: tuple[str, ...] | None = None) -> tuple[list[str], list[str]]:
    """(report lines, failures) over both themes and every accent."""
    accents = accents or ACCENTS
    base, blocks = parse_tokens(css), parse_accents(css)
    failures = [f'{a}: no :root[data-accent="{a}"] block in tokens.css' for a in accents
                if a != DEFAULT_ACCENT and a not in blocks]
    report: list[str] = []
    for theme, accent, (fg, bg, minimum, what) in plan_checks(css, pairs, accents):
        label = f"{theme}/{accent}" if accent else theme
        tokens = {**base[theme], **(blocks.get(accent or "", {}).get(theme, {}))}
        try:
            r = ratio(resolve(tokens, fg), resolve(tokens, bg))
        except (KeyError, ValueError) as exc:
            failures.append(f"{label}: {what}: {exc}")
            report.append(f"  MISSING [{label}] {what}: {exc}")
            continue
        if r < minimum:
            failures.append(f"{label}: {what}: {r:.2f}:1 < {minimum}:1 ({fg} on {bg})")
        report.append(f"  {'FAIL' if r < minimum else 'ok  '} {r:5.2f}:1  (min {minimum})  [{label}]  {what}  {fg} on {bg}")
    return report, failures


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_TOKENS
    if not path.is_file():
        print(f"tokens file not found: {path}")
        return 1
    css = path.read_text(encoding="utf-8")
    report, failures = check(css)
    print("\n".join(report))
    total = len(plan_checks(css))
    print(f"\n{total - len(failures)} of {total} checks pass ({len(PAIRS)} pairs, {len(THEMES)} themes, {len(ACCENTS)} accents)")
    if failures:
        print("\nFAILURES:\n  " + "\n  ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
