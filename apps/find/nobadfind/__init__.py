"""NOBAD Find: private, offline search over your own files."""
import os as _os
import sys as _sys

_BLAS = "OPENBLAS_NUM_THREADS"


def _one_blas_thread():
    """numpy's OpenBLAS reserves about 32 MB of committed memory per CPU thread as it loads: 515 MB on a 16-thread
    PC, in every process that imports numpy (ROADMAP §2 cause 2, docs/measurements.md). Find's numpy work (scoring
    vectors, one small PCA fit) runs as fast or faster on one thread, and the models have their own thread pools.

    Pool workers (started with --multiprocessing-fork) keep the variable: they load numpy later, if at all, and
    start no programs. The main process loads numpy now with it and puts it back, so programs Find opens don't
    inherit it. A value the user set is left alone."""
    if _BLAS in _os.environ:
        return
    _os.environ[_BLAS] = "1"
    if "--multiprocessing-fork" in _sys.argv:
        return
    try:
        import importlib
        importlib.import_module("numpy")
    except ImportError:
        pass
    finally:
        _os.environ.pop(_BLAS, None)


_one_blas_thread()
