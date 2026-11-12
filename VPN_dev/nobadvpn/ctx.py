"""Process-wide singletons, wired up by app.init(). Modules read them at call time,
which keeps the import graph acyclic and lets tests substitute fakes."""


import threading


class _Ctx:
    quit_event = threading.Event()
    started = threading.Event()   # set when the background start-up (adopt, cleanup, tasks) has finished
    settings = None
    tunnel = None
    usage = None
    smart = None
    tray = None
    netwatch = None
    niagent = None    # Network Intelligence fix agent (netintel.agent.FixAgent)
    windows = None
    updater = None
    quitting = False
    state_hooks = []  # callables returning extra keys for the UI state


ctx = _Ctx()
