from __future__ import annotations

from datetime import UTC, datetime

from security.secret_scanner import redact_text

from deployment.deployment_job import (
    DeploymentArtifact,
    DeploymentPreview,
    DeploymentRun,
    DeploymentRunStatus,
    DeploymentStageEvent,
    DeploymentStageRecord,
)


MAX_STAGE_EXCERPT_BYTES = 8 * 1024


def bounded_excerpt(existing: str, addition: str, *, limit: int = MAX_STAGE_EXCERPT_BYTES) -> str:
    combined = "\n".join(part for part in [existing, redact_text(addition)] if part)
    encoded = combined.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return combined
    marker = b"\n... output truncated ...\n"
    available = max(0, limit - len(marker))
    head_size = available // 2
    tail_size = available - head_size
    clipped = encoded[:head_size] + marker + encoded[-tail_size:]
    return clipped.decode("utf-8", errors="replace")


class DeploymentHistoryService:
    def __init__(self, app_data) -> None:  # type: ignore[no-untyped-def]
        self.app_data = app_data
        self._active_stage_ids: dict[str, str] = {}

    def start_run(self, run: DeploymentRun) -> None:
        with self.app_data.session_factory() as session:
            self.app_data.deployment_runs(session).add(run)
            session.commit()

    def update_run_preview(self, run_id: str, preview: DeploymentPreview) -> None:
        with self.app_data.session_factory() as session:
            repo = self.app_data.deployment_runs(session)
            run = repo.get(run_id)
            if run is None:
                return
            run.uploads = preview.uploads
            run.overwrites = preview.overwrites
            run.deletes = preview.deletes
            run.bytes_total = preview.bytes_total
            run.preview_digest = preview.calculated_digest()
            repo.add(run)
            session.commit()

    def begin_stage(self, event: DeploymentStageEvent) -> None:
        if not event.run_id:
            return
        with self.app_data.session_factory() as session:
            stage_repo = self.app_data.deployment_stages(session)
            previous_id = self._active_stage_ids.get(event.run_id)
            if previous_id:
                previous = stage_repo.get(previous_id)
                if previous and previous.finished_at is None:
                    previous.finished_at = event.created_at
                    stage_repo.add(previous)
            sequence = len(stage_repo.list_for_run(event.run_id))
            record = DeploymentStageRecord(
                run_id=event.run_id,
                stage=event.stage,
                message=redact_text(event.message),
                level=event.level,
                sequence=sequence,
                started_at=event.created_at,
            )
            stage_repo.add(record)
            session.commit()
            self._active_stage_ids[event.run_id] = record.id

    def append_stage_output(self, run_id: str, text: str) -> None:
        record_id = self._active_stage_ids.get(run_id)
        if not record_id:
            return
        with self.app_data.session_factory() as session:
            repo = self.app_data.deployment_stages(session)
            record = repo.get(record_id)
            if record is None:
                return
            record.output_excerpt = bounded_excerpt(record.output_excerpt, text)
            repo.add(record)
            session.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: DeploymentRunStatus,
        message: str,
        health_ok: bool | None = None,
        artifact_path: str | None = None,
        rolled_back: bool = False,
        rollback_error: str | None = None,
        retention: int = 100,
    ) -> None:
        now = datetime.now(UTC)
        with self.app_data.session_factory() as session:
            stage_repo = self.app_data.deployment_stages(session)
            active_id = self._active_stage_ids.pop(run_id, None)
            if active_id:
                record = stage_repo.get(active_id)
                if record and record.finished_at is None:
                    record.finished_at = now
                    stage_repo.add(record)
            run_repo = self.app_data.deployment_runs(session)
            run = run_repo.get(run_id)
            if run is None:
                return
            run.status = status
            run.finished_at = now
            run.message = redact_text(message)
            run.health_ok = health_ok
            run.artifact_path = artifact_path
            run.rolled_back = rolled_back
            run.rollback_error = redact_text(rollback_error) if rollback_error else None
            run_repo.add(run)
            run_repo.prune_for_job(run.job_id, keep=retention)
            session.commit()

    def add_artifact(self, artifact: DeploymentArtifact) -> None:
        with self.app_data.session_factory() as session:
            repository = self.app_data.deployment_artifacts(session)
            existing = repository.find_by_path(artifact.job_id, artifact.path)
            if existing is not None:
                artifact.id = existing.id
            repository.add(artifact)
            if artifact.kind.value == "release" and artifact.active:
                repository.set_active(artifact.job_id, artifact.path)
            session.commit()

    def set_active_release(self, job_id: str, path: str | None) -> None:
        with self.app_data.session_factory() as session:
            self.app_data.deployment_artifacts(session).set_active(job_id, path)
            session.commit()

    def apply_artifact_retention(
        self,
        job_id: str,
        kind,
        *,
        keep: int,
        protected_paths: set[str] | None = None,
    ) -> None:  # type: ignore[no-untyped-def]
        with self.app_data.session_factory() as session:
            self.app_data.deployment_artifacts(session).apply_retention(
                job_id,
                kind,
                keep=keep,
                protected_paths=protected_paths,
            )
            session.commit()

    def list_runs(self, job_id: str, *, limit: int = 100) -> list[DeploymentRun]:
        with self.app_data.session_factory() as session:
            return self.app_data.deployment_runs(session).list_for_job(job_id, limit=limit)

    def list_stages(self, run_id: str) -> list[DeploymentStageRecord]:
        with self.app_data.session_factory() as session:
            return self.app_data.deployment_stages(session).list_for_run(run_id)

    def list_artifacts(self, job_id: str) -> list[DeploymentArtifact]:
        with self.app_data.session_factory() as session:
            return self.app_data.deployment_artifacts(session).list_for_job(job_id, restorable_only=True)

    def artifact_by_path(self, job_id: str, path: str) -> DeploymentArtifact | None:
        with self.app_data.session_factory() as session:
            return self.app_data.deployment_artifacts(session).find_by_path(job_id, path)
