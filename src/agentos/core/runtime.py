"""Minimal tool runtime with policy checks and an in-memory audit trail."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from agentos.core.policy import ExecutionPolicy

ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class AuditEvent:
    timestamp: str
    tool_name: str
    allowed: bool
    outcome: str


class ToolRuntime:
    """Executes registered tools only after an explicit policy decision."""

    def __init__(self, policy: ExecutionPolicy) -> None:
        self.policy = policy
        self._tools: dict[str, ToolHandler] = {}
        self.audit_log: list[AuditEvent] = []

    def register(self, name: str, handler: ToolHandler) -> None:
        if not name or name in self._tools:
            raise ValueError("Tool name must be non-empty and unique.")
        self._tools[name] = handler

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        approved: bool = False,
    ) -> Any:
        decision = self.policy.evaluate(name, approved=approved)
        if not decision.allowed:
            self._record(name, False, decision.reason)
            raise PermissionError(decision.reason)

        handler = self._tools.get(name)
        if handler is None:
            self._record(name, False, "Tool is allowlisted but not registered.")
            raise LookupError(f"Tool '{name}' is not registered.")

        try:
            result = handler(arguments or {})
        except Exception as exc:
            self._record(name, True, f"Execution failed: {type(exc).__name__}")
            raise

        self._record(name, True, "Execution completed.")
        return result

    def _record(self, name: str, allowed: bool, outcome: str) -> None:
        self.audit_log.append(
            AuditEvent(
                timestamp=datetime.now(UTC).isoformat(),
                tool_name=name,
                allowed=allowed,
                outcome=outcome,
            )
        )
