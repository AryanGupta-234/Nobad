"""status, status_full, pause_for, resume, learned_apps, reset_learned, hardware."""
from ..protocol import INVALID_PARAMS, RpcError, int_param, ok


def methods(api, events=None):
    def reset_learned(params, conn=None):
        exe = params.get("exe")
        if not (exe is None or isinstance(exe, str)):
            raise RpcError(INVALID_PARAMS, "'exe' must be a program name, or null to forget every app")
        return ok(api.reset_learned(exe))

    return {"status": lambda params, conn=None: api.status_brief(),
            "status_full": lambda params, conn=None: api.status(),
            "pause_for": lambda params, conn=None: ok(api.pause_for(int_param(params, "seconds"))),
            "resume": lambda params, conn=None: ok(api.resume()),
            "learned_apps": lambda params, conn=None: {"apps": list(api.learned_apps() or [])},
            "reset_learned": reset_learned,
            "hardware": lambda params, conn=None: dict(api.hardware())}
