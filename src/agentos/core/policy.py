"""Explicit capability policy for tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str
    approval_required: bool = False


@dataclass(slots=True)
class ExecutionPolicy:
    """Deny-by-default policy with a separate approval gate for sensitive tools."""

    allowed_tools: set[str] = field(default_factory=set)
    approval_required_tools: set[str] = field(default_factory=set)

    def evaluate(self, tool_name: str, *, approved: bool = False) -> PolicyDecision:
        if tool_name not in self.allowed_tools:
            return PolicyDecision(False, f"Tool '{tool_name}' is not allowlisted.")
        if tool_name in self.approval_required_tools and not approved:
            return PolicyDecision(
                False,
                f"Tool '{tool_name}' requires explicit approval.",
                approval_required=True,
            )
        return PolicyDecision(True, "Allowed by execution policy.")
