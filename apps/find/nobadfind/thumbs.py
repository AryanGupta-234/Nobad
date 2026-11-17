"""Result previews: Windows' own thumbnails (the same cache and thumbnail handlers Explorer uses), as data: URLs.

Only for photos, videos and PDFs, only for files in the index (the page asks by result id, never by path), only
when the file is still there. Nothing is decoded by NOBAD Find itself. Kept in a small memory cache.
"""
import base64
import collections
import os
import threading

SIZE = 96                                       # px; shown at 48 px, sharp on high-DPI screens
KINDS = {"image", "video", "pdf"}
TYPES = {"image/bmp", "image/png", "image/jpeg"}
MAX_BYTES = 256 * 1024
_cache = collections.OrderedDict()              # (path, mtime) -> data URL ("" = Windows has no preview)
_lock = threading.Lock()
CACHE_SIZE = 400


def data_url(path, mtime):
    key = (path, mtime)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    url = _make(path)
    with _lock:
        _cache[key] = url
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return url


def _make(path):
    if not os.path.isfile(path):
        return ""
    try:
        from winrt.windows.storage import StorageFile
        from winrt.windows.storage.fileproperties import ThumbnailMode, ThumbnailOptions
        from winrt.windows.storage.streams import DataReader
        f = StorageFile.get_file_from_path_async(path).get()
        th = f.get_thumbnail_async(ThumbnailMode.SINGLE_ITEM, SIZE, ThumbnailOptions.RESIZE_THUMBNAIL).get()
        if th is None or th.content_type not in TYPES or not 0 < th.size <= MAX_BYTES:
            return ""
        r = DataReader(th.get_input_stream_at(0))
        n = r.load_async(th.size).get()
        buf = bytearray(n)
        r.read_bytes(buf)
        return f"data:{th.content_type};base64," + base64.b64encode(bytes(buf)).decode("ascii")
    except Exception:                           # no preview: the result keeps its kind badge
        return ""
