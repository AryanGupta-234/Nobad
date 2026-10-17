from agentos.core.models import StepExecutionResult, StepStatus, TaskExecutionResult, TaskStatus


def test_execution_results_are_typed_and_serializable() -> None:
    step = StepExecutionResult(
        step_id="collect",
        status=StepStatus.SUCCEEDED,
        started_at="2026-10-17T00:00:00+00:00",
        finished_at="2026-10-17T00:00:01+00:00",
        output={"items": 3},
    )
    task = TaskExecutionResult(
        task_id="task-1",
        status=TaskStatus.SUCCEEDED,
        started_at=step.started_at,
        finished_at=step.finished_at,
        steps=(step,),
        summary="Collected three items",
    )

    assert task.status is TaskStatus.SUCCEEDED
    assert task.steps[0].output == {"items": 3}
    assert task.steps[0].status is StepStatus.SUCCEEDED
