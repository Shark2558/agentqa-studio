"""The Docker build context must keep every source file the image needs. `.dockerignore` once said `**/live`, which hid
the React app's own folders (frontend/src/lib/live, frontend/src/components/live): the image's `npm run build` failed
at once, from M1.3 until GitHub's first run showed it. This reads `.dockerignore` with Docker's matching rules (the last
matching rule wins; a rule that matches a folder covers everything inside it) and checks the tracked source files.
Inside the image there is no repository, so it skips there."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
IGNORE_FILE = REPO / ".dockerignore"
NEEDED = ("frontend/src/", "backend/agentqa/", "backend/tests/", "backend/tools/", "backend/demo/")


def _regex(pattern: str) -> re.Pattern:
    """Docker's pattern: * stays inside a folder name, ** crosses folders, ? is one character."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*" and pattern[i + 1:i + 2] == "*":
            i += 2
            if pattern[i:i + 1] == "/":
                i += 1
                out.append("(.*/)?")
            else:
                out.append(".*")
            continue
        out.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
        i += 1
    return re.compile("".join(out))


def parse(text: str) -> list[tuple[bool, re.Pattern]]:
    """(re-included?, regex) for each rule, in order; comments and blank lines dropped."""
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        keep = line.startswith("!")
        rules.append((keep, _regex(line.lstrip("!").strip().strip("/"))))
    return rules


def ignored(path: str, rules: list[tuple[bool, re.Pattern]]) -> bool:
    parts = path.split("/")
    candidates = ["/".join(parts[:n]) for n in range(1, len(parts) + 1)]      # the folders above it, then the file
    verdict = False
    for keep, rx in rules:
        if any(rx.fullmatch(c) for c in candidates):
            verdict = not keep
    return verdict


def test_the_matcher_follows_docker_rules():
    rules = parse("# c\n**/live\nbackend/projects/*\n!backend/projects/README.txt\n*.log\n")
    assert ignored("frontend/src/lib/live/board.ts", rules)           # **/ = any depth, and everything inside
    assert ignored("backend/projects/demo/x.yaml", rules)
    assert not ignored("backend/projects/README.txt", rules)           # re-included by the ! rule after it
    assert not ignored("backend/agentqa/live.py", rules)               # a name is not a prefix of a name
    assert ignored("a.log", rules) and not ignored("sub/a.log", rules)   # * does not cross a folder


def test_the_image_build_context_keeps_every_source_file_it_needs():
    listing = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    if not IGNORE_FILE.is_file() or listing.returncode != 0:
        pytest.skip("not inside the repository (the image has no .git or .dockerignore)")
    rules = parse(IGNORE_FILE.read_text(encoding="utf-8"))
    hidden = [f for f in listing.stdout.splitlines() if f.startswith(NEEDED) and ignored(f, rules)]
    assert hidden == [], f"{len(hidden)} tracked files left out of the image build by .dockerignore, e.g. {hidden[:4]}"
