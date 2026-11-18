"""hello and subscribe."""
from ...const import APP_NAME, APP_VER
from ..events import EVENTS
from ..protocol import INVALID_PARAMS, PROTOCOL, RpcError


def methods(api, events=None):
    def hello(params, conn=None):
        return {"protocol": PROTOCOL, "app": APP_NAME, "version": APP_VER, "events": sorted(EVENTS)}

    def subscribe(params, conn=None):
        names = params.get("events")
        if not isinstance(names, list) or not all(isinstance(e, str) for e in names):
            raise RpcError(INVALID_PARAMS, "'events' must be a list of names")
        if events is None or conn is None:
            return {"events": []}
        return {"events": events.subscribe(conn, names)}

    return {"hello": hello, "subscribe": subscribe}
