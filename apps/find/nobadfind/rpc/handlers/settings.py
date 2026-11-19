"""get_settings, set_settings, pick_folder, rescan, wipe, scope_info, turbo_state, turbo_set.

Every value goes through settings.coerce inside Api.set_settings, exactly as for the WebView page. pick_folder shows
Windows' folder dialog from the engine, so the UI never hands the engine a folder path of its own."""
import threading

from ..protocol import INVALID_PARAMS, RpcError, bool_param, ok, str_param

_asking = threading.Lock()          # one turbo permission prompt at a time
BUSY = "Windows is already asking for permission. Answer that window first."


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

    def turbo_set(params, conn=None):
        on = bool_param(params, "on")
        if not _asking.acquire(blocking=False):
            return {"ok": False, "error": BUSY, "state": api.turbo_state()}
        try:
            r = api.turbo_set(on) or {}
        finally:
            _asking.release()
        out = ok(r)
        out["state"] = r.get("state") if isinstance(r.get("state"), dict) else api.turbo_state()
        if events is not None:
            events.turbo(out["state"])
        return out

    return {"get_settings": lambda params, conn=None: api.get_settings(),
            "scope_info": lambda params, conn=None: api.scope_info(),
            "turbo_state": lambda params, conn=None: api.turbo_state(),
            "turbo_set": turbo_set,
            "set_settings": set_settings,
            "pick_folder": pick_folder,
            "rescan": lambda params, conn=None: ok(api.rescan()),
            "wipe": lambda params, conn=None: ok(api.wipe(str_param(params, "confirm")))}
