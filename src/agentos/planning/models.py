"""Typed task and plan contracts with dependency validation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TaskRequest:
    goal: str
    context: str = ""
    max_steps: int = 20

    def __post_init__(self) -> None:
        if not self.goal.strip():
            raise ValueError("Task goal must not be empty.")
        if self.max_steps < 1:
            raise ValueError("max_steps must be at least 1.")


@dataclass(frozen=True, slots=True)
class PlanStep:
    step_id: str
    description: str
    required_tools: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


@dataclass(slots=True)
class TaskPlan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)

    def validate(self, *, max_steps: int = 20) -> None:
        if not self.goal.strip():
            raise ValueError("Plan goal must not be empty.")
        if len(self.steps) > max_steps:
            raise ValueError(f"Plan exceeds the {max_steps}-step limit.")

        identifiers = [step.step_id for step in self.steps]
        if any(not identifier.strip() for identifier in identifiers):
            raise ValueError("Every plan step needs a non-empty identifier.")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Plan step identifiers must be unique.")

        known = set(identifiers)
        for step in self.steps:
            if not step.description.strip():
                raise ValueError(f"Step '{step.step_id}' needs a description.")
            missing = set(step.depends_on) - known
            if missing:
                raise ValueError(
                    f"Step '{step.step_id}' has unknown dependencies: {sorted(missing)}"
                )
            if step.step_id in step.depends_on:
                raise ValueError(f"Step '{step.step_id}' cannot depend on itself.")

        self.topological_order()

    def topological_order(self) -> list[PlanStep]:
        """Return a stable dependency order; raise when the graph contains a cycle."""
        by_id = {step.step_id: step for step in self.steps}
        pending = {step.step_id: set(step.depends_on) for step in self.steps}
        ordered: list[PlanStep] = []

        while pending:
            ready = sorted(
                step_id for step_id, dependencies in pending.items() if not dependencies
            )
            if not ready:
                raise ValueError("Plan dependencies contain a cycle.")

            for step_id in ready:
                ordered.append(by_id[step_id])
                pending.pop(step_id)
            for dependencies in pending.values():
                dependencies.difference_update(ready)

        return ordered
