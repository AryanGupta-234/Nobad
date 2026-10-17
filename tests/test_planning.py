import pytest

from agentos.planning.models import PlanStep, TaskPlan, TaskRequest


def test_task_request_validates_goal_and_step_budget() -> None:
    assert TaskRequest("Prepare a report", max_steps=3).max_steps == 3
    with pytest.raises(ValueError):
        TaskRequest(" ")
    with pytest.raises(ValueError):
        TaskRequest("Valid goal", max_steps=0)


def test_plan_returns_dependency_order() -> None:
    plan = TaskPlan(
        goal="Build and verify",
        steps=[
            PlanStep("verify", "Verify output", depends_on=("build",)),
            PlanStep("build", "Build artifact"),
            PlanStep("report", "Report result", depends_on=("verify",)),
        ],
    )

    plan.validate()
    assert [step.step_id for step in plan.topological_order()] == [
        "build",
        "verify",
        "report",
    ]


def test_plan_rejects_unknown_dependencies_and_cycles() -> None:
    unknown = TaskPlan("Goal", [PlanStep("a", "A", depends_on=("missing",))])
    with pytest.raises(ValueError, match="unknown dependencies"):
        unknown.validate()

    cyclic = TaskPlan(
        "Goal",
        [
            PlanStep("a", "A", depends_on=("b",)),
            PlanStep("b", "B", depends_on=("a",)),
        ],
    )
    with pytest.raises(ValueError, match="cycle"):
        cyclic.validate()


def test_plan_enforces_step_budget_and_unique_ids() -> None:
    too_large = TaskPlan("Goal", [PlanStep("a", "A"), PlanStep("b", "B")])
    with pytest.raises(ValueError, match="step limit"):
        too_large.validate(max_steps=1)

    duplicate = TaskPlan("Goal", [PlanStep("a", "A"), PlanStep("a", "B")])
    with pytest.raises(ValueError, match="unique"):
        duplicate.validate()
