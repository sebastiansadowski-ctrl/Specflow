"""Workspace projektu: katalog, `git init`, `specify init`, commit po każdym zadaniu.

Katalog jest montowany w kontenerze Docker z agentem jako jedyny dostępny katalog.
"""

from specflow.workspace.manager import (
    AGENT_AUTHOR,
    SPEC_KIT_VERSION,
    Runner,
    Workspace,
    WorkspaceError,
    run_command,
    slugify,
)

__all__ = [
    "AGENT_AUTHOR",
    "SPEC_KIT_VERSION",
    "Runner",
    "Workspace",
    "WorkspaceError",
    "run_command",
    "slugify",
]
