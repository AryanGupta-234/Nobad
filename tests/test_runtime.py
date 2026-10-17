import pytest

from agentos.core.policy import ExecutionPolicy
from agentos.core.runtime import ToolRuntime


def test_runtime_executes_registered_allowlisted_tool() -> None:
    runtime = ToolRuntime(ExecutionPolicy(allowed_tools={"math.add"}))
    runtime.register("math.add", lambda args: args["a"] + args["b"])

    assert runtime.execute("math.add", {"a": 2, "b": 3}) == 5
    assert runtime.audit_log[-1].allowed


def test_runtime_blocks_non_allowlisted_tool() -> None:
    runtime = ToolRuntime(ExecutionPolicy())
    runtime.register("system.shell", lambda _: "should not run")

    with pytest.raises(PermissionError):
        runtime.execute("system.shell")

    assert not runtime.audit_log[-1].allowed


def test_runtime_requires_approval_for_sensitive_tool() -> None:
    policy = ExecutionPolicy(
        allowed_tools={"cloud.deploy"},
        approval_required_tools={"cloud.deploy"},
    )
    runtime = ToolRuntime(policy)
    runtime.register("cloud.deploy", lambda _: "deployed")

    with pytest.raises(PermissionError):
        runtime.execute("cloud.deploy")

    assert runtime.execute("cloud.deploy", approved=True) == "deployed"
