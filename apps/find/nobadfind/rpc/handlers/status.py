"""status, status_full, pause_for, resume, learned_apps, reset_learned, hardware."""
from ..protocol import INVALID_PARAMS, RpcError, int_param, ok


MAX_EXE = 260


def methods(api, events=None):
    def reset_learned(params, conn=None):
        exe = params.get("exe")
        if not (exe is None or (isinstance(exe, str) and len(exe) <= MAX_EXE)):
            raise RpcError(INVALID_PARAMS, "'exe' must be a program name, or null to forget every app")
        return ok(api.reset_learned(exe))

    def pause_for(params, conn=None):
        seconds = int_param(params, "seconds")
        if seconds < 1:
            raise RpcError(INVALID_PARAMS, "'seconds' must be 1 or more")
        return ok(api.pause_for(seconds))

    return {"status": lambda params, conn=None: api.status_brief(),
            "status_full": lambda params, conn=None: api.status(),
            "pause_for": pause_for,
            "resume": lambda params, conn=None: ok(api.resume()),
            "learned_apps": lambda params, conn=None: {"apps": list(api.learned_apps() or [])},
            "reset_learned": reset_learned,
            "hardware": lambda params, conn=None: dict(api.hardware())}
