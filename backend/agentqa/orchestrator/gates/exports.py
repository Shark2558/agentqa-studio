"""Downloads: each export is written by the engine's own writer into a folder of its own and read back from there, so
nothing in reports/ is touched, two downloads (or a report stage running beside them) cannot swap files, and a writer
that failed is never answered with an older file."""
from __future__ import annotations

import copy
import logging
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from agentqa.config import Project
from agentqa.orchestrator.gates import GateError

log = logging.getLogger(__name__)
NOT_WRITTEN = "The file could not be written (is it open in another program?); the log has the details"


def download_name(text: str, suffix: str) -> str:
    """A file name of plain letters, digits and dashes (a header can only carry those safely), e.g. demo-defects.csv."""
    stem = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-") or "project"
    return f"{stem}-{suffix}"


def build(project: Project, write: Callable[[Project], str | Path]) -> bytes:
    """Run `write` with the project's reports folder pointed at a fresh temporary folder; the bytes it wrote, or 503."""
    with tempfile.TemporaryDirectory(dir=project.state, prefix="export-", ignore_cleanup_errors=True) as tmp:
        scratch = copy.copy(project)
        scratch.reports_dir = Path(tmp)
        try:
            path = Path(write(scratch))
            if not path.is_file() or not path.resolve().is_relative_to(Path(tmp).resolve()):
                raise GateError(503, "unavailable", NOT_WRITTEN)
            return path.read_bytes()
        except OSError as exc:
            log.warning("export for %s failed: %s", project.root.name, exc)
            raise GateError(503, "unavailable", NOT_WRITTEN) from exc
