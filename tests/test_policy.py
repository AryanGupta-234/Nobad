import pytest

from agentos.core.policy import ExecutionPolicy


def test_policy_denies_tools_by_default() -> None:
    decision = ExecutionPolicy().evaluate("filesystem.read")
    assert not decision.allowed
    assert "not allowlisted" in decision.reason


def test_policy_allows_allowlisted_tool() -> None:
    decision = ExecutionPolicy(allowed_tools={"notes.search"}).evaluate("notes.search")
    assert decision.allowed


def test_sensitive_tool_requires_approval() -> None:
    policy = ExecutionPolicy(
        allowed_tools={"cloud.deploy"},
        approval_required_tools={"cloud.deploy"},
    )
    blocked = policy.evaluate("cloud.deploy")
    approved = policy.evaluate("cloud.deploy", approved=True)

    assert not blocked.allowed
    assert blocked.approval_required
    assert approved.allowed
