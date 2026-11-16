from __future__ import annotations

from dataclasses import dataclass
from PySide6.QtGui import QFont


@dataclass(frozen=True, slots=True)
class ThemeTokens:
    """Raycast / Linear-inspired design tokens for Remote File Manager."""
    canvas: str = "#09090b"          # Window base background
    surface: str = "#111114"         # Panels, sidebars, headers
    surface_card: str = "#141418"    # Elevated items, table rows, inputs
    surface_hover: str = "#1e1e24"   # Hover state for interactive items
    surface_active: str = "#222228"  # Active / selected state
    border: str = "#1e1e24"          # 1px subtle border hierarchy
    border_subtle: str = "#151518"   # Subtle separators between items
    border_focus: str = "#6366f1"    # Focus outline
    text: str = "#f4f4f5"            # Primary text
    text_muted: str = "#a1a1aa"      # Secondary text / labels
    text_dim: str = "#71717a"        # Disabled / tertiary info
    accent: str = "#6366f1"          # Indigo primary accent
    accent_hover: str = "#4f46e5"    # Indigo hover
    accent_subtle: str = "rgba(99, 102, 241, 0.12)" # Accent background tint
    success: str = "#10b981"         # Emerald synced / connected
    success_subtle: str = "rgba(16, 185, 129, 0.12)"
    warning: str = "#f59e0b"         # Amber sync conflict / alert
    warning_subtle: str = "rgba(245, 158, 11, 0.12)"
    danger: str = "#ef4444"          # Rose delete / error
    danger_subtle: str = "rgba(239, 68, 68, 0.12)"
    input_background: str = "#141418"
    terminal_background: str = "#09090b"


DEFAULT_THEME = ThemeTokens()


def get_ui_font(size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Return primary UI font with cross-platform fallback."""
    font = QFont()
    font.setFamilies(["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "Cantarell", "Ubuntu", "sans-serif"])
    font.setPointSize(size)
    font.setWeight(weight)
    return font


def get_mono_font(size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Return monospace font with tabular figures for code, paths, and numbers."""
    font = QFont()
    font.setFamilies(["JetBrains Mono", "Fira Code", "Cascadia Code", "SF Mono", "Consolas", "DejaVu Sans Mono", "monospace"])
    font.setPointSize(size)
    font.setWeight(weight)
    # Enable tabular figures if supported by font engine
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font
