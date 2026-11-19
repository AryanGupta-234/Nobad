"""get_settings, set_settings, pick_folder, rescan, wipe.

Every value goes through settings.coerce inside Api.set_settings, exactly as for the WebView page. pick_folder shows
Windows' folder dialog from the engine, so the UI never hands the engine a folder path of its own."""
from ..protocol import INVALID_PARAMS, RpcError, ok, str_param


def methods(api, events=None):
    def set_settings(params, conn=None):
        changes = params.get("changes")
        if not isinstance(changes, dict):
            raise RpcError(INVALID_PARAMS, "'changes' must be an object of setting names and values")
        r = api.set_settings(changes)
        return {"changed": list((r or {}).get("changed") or []), "settings": api.get_settings()}

    def pick_folder(params, conn=None):
        """busy: a folder dialog is already open (it was brought to the front); path is "" then."""
        r = api.pick_folder() or {}
        return {"path": str(r.get("path") or ""), "busy": bool(r.get("busy"))}

    return {"get_settings": lambda params, conn=None: api.get_settings(),
            "set_settings": set_settings,
            "pick_folder": pick_folder,
            "rescan": lambda params, conn=None: ok(api.rescan()),
            "wipe": lambda params, conn=None: ok(api.wipe(str_param(params, "confirm")))}
