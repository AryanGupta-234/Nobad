from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True, slots=True)
class DiffHunk:
    tag: str
    left_start: int
    left_end: int
    right_start: int
    right_end: int

    @property
    def changed(self) -> bool:
        return self.tag != "equal"


class TextDiffEngine:
    def compare(self, left: str, right: str) -> list[DiffHunk]:
        matcher = SequenceMatcher(None, left.splitlines(), right.splitlines(), autojunk=False)
        return [
            DiffHunk(tag, left_start, left_end, right_start, right_end)
            for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes()
        ]
