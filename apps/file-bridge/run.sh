#!/usr/bin/env bash
set -euo pipefail

# Force Qt to use the generic theme instead of GNOME gtk3 to prevent GLib-GIO schema crashes
export QT_QPA_PLATFORMTHEME="generic"
export QT_STYLE_OVERRIDE="Fusion"

exec uv run python -m app.main "$@"
