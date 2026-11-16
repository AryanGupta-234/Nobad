from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from deployment.deployment_job import (
    DeploymentMode,
    DeploymentStrategy,
    HealthCheckOrigin,
)
from ui.deployment_panel import DeploymentPanel


def test_deployment_panel_builds_typed_job(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    panel = DeploymentPanel()
    panel.name.setText("Production")
    panel.mode.setCurrentIndex(1)
    panel.strategy.setCurrentIndex(1)
    panel.health_url.setText("https://example.com/health")
    panel.health_origin.setCurrentIndex(1)

    job = panel.current_job()

    assert job.name == "Production"
    assert job.mode == DeploymentMode.MIRROR
    assert job.strategy == DeploymentStrategy.ATOMIC_RELEASE
    assert job.health_check.http_origin == HealthCheckOrigin.REMOTE
    assert panel.model.columnCount() == 5
    assert panel.output_tabs.count() == 3
    panel.close()
    app.processEvents()
