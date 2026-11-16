from __future__ import annotations

from file_ops.conflict_policy import ConflictDecision, ConflictPolicy


class ConflictResolver:
    def __init__(self, default_policy: ConflictPolicy = ConflictPolicy.ASK_EVERY_TIME) -> None:
        self.default_policy = default_policy

    def resolve(self, *, source_path: str, destination_path: str, apply_to_all: bool = False) -> ConflictDecision:
        if self.default_policy == ConflictPolicy.RENAME:
            return ConflictDecision(
                policy=ConflictPolicy.RENAME,
                apply_to_all=apply_to_all,
                alternate_name=self._renamed_path(destination_path),
            )
        return ConflictDecision(policy=self.default_policy, apply_to_all=apply_to_all)

    def _renamed_path(self, destination_path: str) -> str:
        if "." not in destination_path.rsplit("/", 1)[-1]:
            return f"{destination_path}.copy"
        stem, suffix = destination_path.rsplit(".", 1)
        return f"{stem}.copy.{suffix}"

