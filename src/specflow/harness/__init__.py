"""Adaptery harnessu (ADR-0002, ADR-0005).

Port `Harness` + nasz słownik zdarzeń. Implementacje:
- `mock`     - udawany agent ze scenariuszami, do testów i CI,
- `opencode` - `opencode serve` w kontenerze Docker, sterowany przez HTTP.
"""

from specflow.harness.base import (
    CommandPrompt,
    CommandResult,
    Harness,
    HarnessError,
    Prompt,
    Session,
    SessionSpec,
    TextPrompt,
)
from specflow.harness.events import (
    AgentEvent,
    AgentMessage,
    AgentReport,
    FileChanged,
    RunFinished,
    ToolCall,
    ToolResult,
    Usage,
    build_run_finished,
    parse_agent_report,
)
from specflow.harness.permissions import AgentProfile, PermissionRule, rules_for

__all__ = [
    "AgentEvent",
    "AgentMessage",
    "AgentProfile",
    "AgentReport",
    "CommandPrompt",
    "CommandResult",
    "FileChanged",
    "Harness",
    "HarnessError",
    "PermissionRule",
    "Prompt",
    "RunFinished",
    "Session",
    "SessionSpec",
    "TextPrompt",
    "ToolCall",
    "ToolResult",
    "Usage",
    "build_run_finished",
    "parse_agent_report",
    "rules_for",
]
