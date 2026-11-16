from __future__ import annotations

from file_ops.conflict_policy import ConflictPolicy
from transfers.conflict_resolver import ConflictResolver


def test_default_conflict_policy_is_ask() -> None:
    decision = ConflictResolver().resolve(source_path="a.txt", destination_path="b.txt")
    assert decision.policy == ConflictPolicy.ASK_EVERY_TIME


def test_rename_policy_generates_alternate_name() -> None:
    decision = ConflictResolver(ConflictPolicy.RENAME).resolve(source_path="a.txt", destination_path="/tmp/b.txt")
    assert decision.policy == ConflictPolicy.RENAME
    assert decision.alternate_name == "/tmp/b.copy.txt"

