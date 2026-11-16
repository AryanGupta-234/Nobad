from __future__ import annotations

from datetime import datetime, timezone

from sync.diff_engine import SyncAction, SyncManifestEntry, SyncTargetSide
from sync.sync_job import SyncJob, SyncMode
from sync.sync_planner import SyncPlanner


def test_sync_planner_skips_default_ignored_paths() -> None:
    job = SyncJob("Upload", SyncMode.LOCAL_TO_REMOTE, "local", "remote")
    preview = SyncPlanner().preview_from_paths(job, ["src/app.py", "node_modules/pkg/index.js", ".git/config"])

    assert preview.uploads == ["src/app.py"]
    assert "node_modules/pkg/index.js" in preview.skipped
    assert ".git/config" in preview.skipped


def test_sync_planner_detects_upload_overwrite_and_skip() -> None:
    now = datetime.now(timezone.utc)
    job = SyncJob("Upload", SyncMode.LOCAL_TO_REMOTE, "local", "remote")
    preview = SyncPlanner().preview_from_manifests(
        job,
        [
            SyncManifestEntry("index.html", size=100, modified_at=now),
            SyncManifestEntry("app.js", size=50, modified_at=now),
            SyncManifestEntry("same.css", size=10, modified_at=now),
        ],
        [
            SyncManifestEntry("app.js", size=51, modified_at=now),
            SyncManifestEntry("same.css", size=10, modified_at=now),
        ],
    )

    assert preview.uploads == ["index.html"]
    assert preview.overwrites == ["app.js"]
    assert "same.css" in preview.skipped
    assert [entry.action for entry in preview.entries if entry.path == "app.js"] == [SyncAction.OVERWRITE]


def test_two_way_preview_marks_changed_common_files_as_conflicts() -> None:
    job = SyncJob("Two way", SyncMode.TWO_WAY, "local", "remote")
    preview = SyncPlanner().preview_from_manifests(
        job,
        [SyncManifestEntry("config.json", size=100)],
        [SyncManifestEntry("config.json", size=200)],
    )

    assert preview.conflicts == ["config.json"]
    assert preview.entries[0].action == SyncAction.CONFLICT


def test_local_to_remote_mirror_marks_remote_only_files_for_delete() -> None:
    job = SyncJob("Upload", SyncMode.LOCAL_TO_REMOTE, "local", "remote")
    preview = SyncPlanner().preview_from_manifests(
        job,
        [SyncManifestEntry("index.html", size=100)],
        [SyncManifestEntry("old.html", size=50)],
    )

    delete_entries = [entry for entry in preview.entries if entry.action == SyncAction.DELETE]
    assert preview.deletes == ["old.html"]
    assert delete_entries[0].target_side == SyncTargetSide.REMOTE


def test_remote_to_local_mirror_marks_local_only_files_for_delete() -> None:
    job = SyncJob("Download", SyncMode.REMOTE_TO_LOCAL, "remote", "local")
    preview = SyncPlanner().preview_from_manifests(
        job,
        [SyncManifestEntry("remote.txt", size=100)],
        [SyncManifestEntry("local-only.txt", size=50)],
    )

    delete_entries = [entry for entry in preview.entries if entry.action == SyncAction.DELETE]
    assert preview.deletes == ["local-only.txt"]
    assert delete_entries[0].target_side == SyncTargetSide.LOCAL


def test_two_way_sync_moves_unique_files_without_delete_inference() -> None:
    job = SyncJob("Two way", SyncMode.TWO_WAY, "local", "remote")
    preview = SyncPlanner().preview_from_manifests(
        job,
        [SyncManifestEntry("local-only.txt", size=100)],
        [SyncManifestEntry("remote-only.txt", size=50)],
    )

    assert preview.uploads == ["local-only.txt"]
    assert preview.downloads == ["remote-only.txt"]
    assert preview.deletes == []


def test_ignored_destination_only_paths_are_not_deleted() -> None:
    job = SyncJob("Upload", SyncMode.LOCAL_TO_REMOTE, "local", "remote")
    preview = SyncPlanner().preview_from_manifests(
        job,
        [],
        [SyncManifestEntry("node_modules/pkg/index.js", size=50)],
    )

    assert preview.deletes == []
    assert "node_modules/pkg/index.js" in preview.skipped
