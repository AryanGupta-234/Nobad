from agentos.core.audit import SQLiteAuditSink
from agentos.core.policy import ExecutionPolicy
from agentos.core.runtime import ToolRuntime


def test_runtime_persists_allowed_and_denied_decisions(tmp_path) -> None:
    sink = SQLiteAuditSink(tmp_path / "audit.sqlite3")
    runtime = ToolRuntime(
        ExecutionPolicy(allowed_tools={"math.add"}),
        audit_sink=sink,
    )
    runtime.register("math.add", lambda args: args["a"] + args["b"])
    runtime.execute("math.add", {"a": 1, "b": 2})

    import pytest

    with pytest.raises(PermissionError):
        runtime.execute("system.shell")

    events = sink.list_events()
    assert len(events) == 2
    assert events[0]["tool_name"] == "system.shell"
    assert events[0]["allowed"] == 0
    assert events[1]["tool_name"] == "math.add"
    assert events[1]["allowed"] == 1
