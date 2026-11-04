"""Safe files: a path the engine stored (evidence, visual images, help-box screenshots) is served only when it resolves
inside one of the project's own result folders and has an allowed type. Pages never send a path: they ask by index."""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from agentqa.config import Project

INLINE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}            # shown in the page
DOWNLOAD = {".zip": "application/zip", ".webm": "video/webm", ".txt": "text/plain", ".json": "application/json"}


class SafeFile(NamedTuple):
    path: Path
    media_type: str
    inline: bool


def allowed_folders(project: Project) -> tuple[Path, ...]:
    return tuple(d.resolve() for d in (project.runs_dir, project.reports_dir, project.root / "visual",
                                       project.state / "assist"))


def is_image(stored: object) -> bool:
    return isinstance(stored, str) and Path(stored).suffix.lower() in INLINE


def _candidate(project: Project, stored: object) -> Path | None:
    """The stored path made absolute, or None before anything is read: not text, a NUL, or another drive or a network
    share (resolving one would contact it)."""
    if not isinstance(stored, str) or not stored or "\x00" in stored:
        return None
    path = Path(stored)
    path = path if path.is_absolute() else project.root / path
    return path if path.drive.lower() == project.root.drive.lower() else None


def safe_file(project: Project, stored: object) -> SafeFile | None:
    """The file to serve for a stored path, or None: missing, outside the allowed folders (after following `..` and
    links), an NTFS stream (`a.png:x.txt`), or of a type not on the lists."""
    path = _candidate(project, stored)
    try:
        real = path.resolve(strict=True) if path else None
    except (OSError, RuntimeError, ValueError):
        return None
    if real is None or ":" in real.name or not real.is_file() \
            or not any(real.is_relative_to(d) for d in allowed_folders(project)):
        return None
    ext = real.suffix.lower()
    if ext in INLINE:
        return SafeFile(real, INLINE[ext], True)
    if ext in DOWNLOAD:
        return SafeFile(real, DOWNLOAD[ext], False)
    return None
