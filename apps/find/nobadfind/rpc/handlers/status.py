"""status: the small subset the prototype shows (level, reason, files, phase, paused)."""


def methods(api, events=None):
    return {"status": lambda params, conn=None: api.status_brief()}
