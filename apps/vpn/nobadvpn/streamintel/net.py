"""Tiny JSON-over-HTTPS client shared by every data source: honest User-Agent, timeouts, up to two polite retries
on 429/5xx/connection errors (honouring Retry-After up to a cap), and typed errors that say *why* data is missing."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from ..const import APP_VER

USER_AGENT = f"NOBAD-VPN/{APP_VER} (+https://github.com/AryanGupta-234/Nobad)"
MAX_RETRY_WAIT = 4.0


class SourceError(Exception):
    """kind: auth | rate | notfound | unavailable | bad"""

    def __init__(self, kind, message, status=None):
        super().__init__(message)
        self.kind, self.status = kind, status


def _kind_for(status):
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "notfound"
    if status == 429:
        return "rate"
    if status and status >= 500:
        return "unavailable"
    return "bad"


def get_bytes(url, params=None, headers=None, timeout=12, opener=None, sleep=time.sleep, max_bytes=8_000_000):
    """GET -> bytes. `opener(request, timeout)` is injectable for tests (default: urllib.request.urlopen)."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    h.update(headers or {})
    if opener is None:
        from .. import reach            # adapts to networks that block a hostname or its DNS
        opener = reach.urlopen
    open_ = opener
    last = None
    for attempt in (1, 2, 3):
        req = urllib.request.Request(url, headers=h)
        try:
            with open_(req, timeout=timeout) as r:
                return r.read(max_bytes + 1)[:max_bytes]
        except urllib.error.HTTPError as e:
            kind = _kind_for(e.code)
            last = SourceError(kind, f"HTTP {e.code}", e.code)
            if kind in ("rate", "unavailable") and attempt < 3:
                try:
                    wait = float(e.headers.get("Retry-After") or 1)
                except (TypeError, ValueError, AttributeError):
                    wait = 1.0
                sleep(min(MAX_RETRY_WAIT, max(0.2, wait)))
                continue
            raise last
        except (urllib.error.URLError, OSError, ValueError) as e:
            # Connection resets happen on some networks (ISPs filtering by TLS name); a short backoff usually gets through.
            last = SourceError("unavailable", f"{type(e).__name__}: {getattr(e, 'reason', e)}")
            if attempt < 3:
                sleep(0.6 * attempt)
                continue
            raise last
    raise last


def get_json(url, params=None, headers=None, timeout=12, opener=None, sleep=time.sleep):
    raw = get_bytes(url, params, headers, timeout, opener, sleep)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise SourceError("bad", f"invalid JSON ({e})")
