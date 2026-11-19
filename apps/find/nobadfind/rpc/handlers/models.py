"""download_model, download_photo_model: only with the download allowed in Settings (the Api checks it); the
progress comes as `download` events."""
from ..protocol import ok


def methods(api, events=None):
    return {"download_model": lambda params, conn=None: ok(api.download_model()),
            "download_photo_model": lambda params, conn=None: ok(api.download_photo_model())}
