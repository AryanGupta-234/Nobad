"""What this PC has (RAM, CPU, graphics card, disk), for Settings -> Models "Your PC". Read once per run.

Every probe fails to a safe default: a missing answer never stops the page from showing."""
import ctypes
import os
import shutil
import threading
from ctypes import wintypes

from . import winapi
from .log import log

_PF_AVX2, _PF_AVX512F = 40, 41
_DXGI_SOFTWARE = 2
_IID_FACTORY1 = (0x770AAE78, 0xF26F, 0x4DBA, bytes([0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87]))

_cache = None
_lock = threading.Lock()


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]


class _AdapterDesc1(ctypes.Structure):
    _fields_ = [("Description", ctypes.c_wchar * 128), ("VendorId", ctypes.c_uint), ("DeviceId", ctypes.c_uint),
                ("SubSysId", ctypes.c_uint), ("Revision", ctypes.c_uint), ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t), ("SharedSystemMemory", ctypes.c_size_t),
                ("LuidLow", ctypes.c_uint), ("LuidHigh", ctypes.c_int), ("Flags", ctypes.c_uint)]


def _method(obj, index, *argtypes):
    """COM method number `index` of the interface pointer `obj`, as a callable (HRESULT result)."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])


def _release(obj):
    _method(obj, 2)(obj)


def adapters():
    """[(name, dedicated video memory in bytes, flags)] for every graphics adapter DXGI lists; [] if it fails."""
    if not winapi.WIN:
        return []
    out = []
    try:
        dxgi = ctypes.WinDLL("dxgi")
        dxgi.CreateDXGIFactory1.argtypes = [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        dxgi.CreateDXGIFactory1.restype = ctypes.c_long
        iid = _GUID(_IID_FACTORY1[0], _IID_FACTORY1[1], _IID_FACTORY1[2], (ctypes.c_ubyte * 8)(*_IID_FACTORY1[3]))
        factory = ctypes.c_void_p()
        if dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0 or not factory.value:
            return []
        try:
            enum = _method(factory, 12, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))      # EnumAdapters1
            for i in range(32):
                ad = ctypes.c_void_p()
                if enum(factory, i, ctypes.byref(ad)) != 0 or not ad.value:
                    break                                                                    # DXGI_ERROR_NOT_FOUND
                try:
                    desc = _AdapterDesc1()
                    if _method(ad, 10, ctypes.POINTER(_AdapterDesc1))(ad, ctypes.byref(desc)) == 0:   # GetDesc1
                        out.append((desc.Description, int(desc.DedicatedVideoMemory), int(desc.Flags)))
                finally:
                    _release(ad)
        finally:
            _release(factory)
    except Exception as e:
        log(f"graphics card check failed: {type(e).__name__}", "warn")
        return []
    return out


def _gpu():
    """(name, vram_gb, directml) of the real adapter with the most video memory."""
    real = [a for a in adapters() if not a[2] & _DXGI_SOFTWARE]
    if not real:
        return "", 0.0, False
    name, vram, _flags = max(real, key=lambda a: a[1])
    try:
        import onnxruntime
        dml = "DmlExecutionProvider" in onnxruntime.get_available_providers()
    except Exception:
        dml = False
    return name.strip(), round(vram / 1073741824, 1), dml


def _physical_cores(threads):
    """Physical cores (GetLogicalProcessorInformationEx, RelationProcessorCore); threads//2 or threads if unknown."""
    try:
        k = ctypes.WinDLL("kernel32")
        fn = k.GetLogicalProcessorInformationEx
        fn.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        fn.restype = wintypes.BOOL
        n = wintypes.DWORD(0)
        fn(0, None, ctypes.byref(n))
        if n.value:
            buf = ctypes.create_string_buffer(n.value)
            if fn(0, buf, ctypes.byref(n)):
                count, off = 0, 0
                while off + 8 <= n.value:
                    rel, size = int.from_bytes(buf[off:off + 4], "little"), int.from_bytes(buf[off + 4:off + 8], "little")
                    if size <= 0:
                        break
                    count += rel == 0
                    off += size
                if count:
                    return min(count, threads)
    except Exception:
        pass
    return max(1, threads // 2) if threads > 1 else 1


def _scan():
    threads = os.cpu_count() or 1
    out = {"ram_gb": 0.0, "cores": threads, "threads": threads, "avx2": False, "avx512_vnni": False,
           "gpu": "", "vram_gb": 0.0, "directml": False, "disk_free_gb": 0.0, "ssd": None}
    if winapi.WIN:
        m = winapi._MEMSTATUS()
        m.dwLength = ctypes.sizeof(m)
        try:
            if winapi.k32.GlobalMemoryStatusEx(ctypes.byref(m)):
                out["ram_gb"] = round(m.ullTotalPhys / 1073741824, 1)
        except Exception:
            pass
        out["cores"] = _physical_cores(threads)
        try:
            k = ctypes.WinDLL("kernel32")
            k.IsProcessorFeaturePresent.argtypes = [wintypes.DWORD]
            out["avx2"] = bool(k.IsProcessorFeaturePresent(_PF_AVX2))
            # Windows has no feature flag for AVX512-VNNI; AVX512F alone doesn't prove it, so VNNI stays unknown (False)
        except Exception:
            pass
        out["gpu"], out["vram_gb"], out["directml"] = _gpu()
    home = os.path.expanduser("~")
    try:
        out["disk_free_gb"] = round(shutil.disk_usage(home).free / 1073741824, 1)
    except OSError:
        pass
    try:
        out["ssd"] = winapi.is_ssd(os.path.splitdrive(home)[0] + "\\")
    except Exception:
        pass
    return out


def scan():
    """The hardware facts, cached for the life of the process."""
    global _cache
    with _lock:
        if _cache is None:
            try:
                _cache = _scan()
            except Exception as e:
                log(f"hardware check failed: {type(e).__name__}", "warn")
                _cache = {"ram_gb": 0.0, "cores": os.cpu_count() or 1, "threads": os.cpu_count() or 1, "avx2": False,
                          "avx512_vnni": False, "gpu": "", "vram_gb": 0.0, "directml": False,
                          "disk_free_gb": 0.0, "ssd": None}
        return _cache
