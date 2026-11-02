"""Orchestrator: the engine's project registry, job runner and live-event reader, shared by the old dashboard
(agentqa.web) and the new API (agentqa.api). Moved out of web/app.py in M0.5; behaviour unchanged."""
from __future__ import annotations


class NotFound(LookupError):
    """A project or live session that does not exist (or a path that tries to escape its folder)."""


class Busy(RuntimeError):
    """A stage is already running for this project."""


class Conflict(ValueError):
    """A project with that name already exists and points at a different application."""
