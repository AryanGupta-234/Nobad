from __future__ import annotations

from file_ops.conflict_policy import ConflictPolicy
from ui.remote_file_panel import RemoteFilePanel


def test_no_conflict_uses_safe_non_interactive_policy() -> None:
    panel = RemoteFilePanel.__new__(RemoteFilePanel)

    decision = panel._conflict_decision_for_preflight(False)

    assert decision is not None
    assert decision.policy == ConflictPolicy.SKIP


def test_actual_conflict_delegates_to_conflict_dialog(monkeypatch) -> None:
    panel = RemoteFilePanel.__new__(RemoteFilePanel)
    expected = object()
    monkeypatch.setattr(panel, "_transfer_conflict_decision", lambda: expected)

    assert panel._conflict_decision_for_preflight(True) is expected
