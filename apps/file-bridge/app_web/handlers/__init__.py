"""API handlers, one module per screen. ``register_all()`` imports them, which registers their ``@handler``s."""
from __future__ import annotations

import importlib

MODULES = ("app_info", "settings")


def register_all() -> None:
    for name in MODULES:
        importlib.import_module(f"app_web.handlers.{name}")
