"""Model downloads and tiers.

download_model, download_photo_model (0.7.0: only with the download allowed in Settings, the Api checks it) stay as
they were. models, model_use, model_download, model_remove, auto_configure, model_language: Settings -> Models
(models.CATALOG). Progress comes as `download` events (id = the model id), changes as `models` events."""
import re

from ..protocol import INVALID_PARAMS, RpcError, choice_param, ok, str_param

_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")
FEATURES = ("text", "photo", "ocr")
FOCUSES = ("english", "multilingual", "hindi")


def _model_id(params):
    v = str_param(params, "id")
    if not _ID.match(v):
        raise RpcError(INVALID_PARAMS, "'id' must be a model id from the models list")
    return v


def _consent(params):
    v = str_param(params, "consent")
    if len(v) > 32:
        raise RpcError(INVALID_PARAMS, "'consent' is at most 32 characters")
    return v


def _use(api, params):
    r = api.model_use(choice_param(params, "feature", FEATURES, None), _model_id(params))
    return {"ok": bool(r.get("ok")), "error": str(r.get("error") or ""), "needs_download": bool(r.get("needs_download"))}


def methods(api, events=None):
    return {"download_model": lambda params, conn=None: ok(api.download_model()),
            "download_photo_model": lambda params, conn=None: ok(api.download_photo_model()),
            "models": lambda params, conn=None: api.models(),
            "model_use": lambda params, conn=None: _use(api, params),
            "model_download": lambda params, conn=None: ok(api.model_download(_model_id(params), _consent(params))),
            "model_remove": lambda params, conn=None: ok(api.model_remove(_model_id(params))),
            "auto_configure": lambda params, conn=None: api.auto_configure(),
            "model_language": lambda params, conn=None: ok(api.model_language(
                choice_param(params, "focus", FOCUSES, None)))}
