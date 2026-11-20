"""ROADMAP Phase 1: what each NOBAD Find process loads and commits (see docs/measurements.md).

These start real Python processes, because what matters is what a fresh process imports."""
import os
import subprocess
import sys

import pytest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER_ARGV = "sys.argv.append('--multiprocessing-fork')"     # how a spawned pool worker starts


def py(code, env=None):
    e = dict(os.environ)
    e.pop("OPENBLAS_NUM_THREADS", None)
    e["PYTHONPATH"] = os.pathsep.join([APP, os.path.join(APP, "tests")])     # procinfo (ctypes; CI has no psutil)
    e.update(env or {})
    r = subprocess.run([sys.executable, "-c", code], cwd=APP, capture_output=True, text=True, timeout=120, env=e)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1]


def test_a_text_reader_does_not_load_numpy():
    """What a text reader imports itself (python -m nobadfind: multiprocessing doesn't run a package's __main__
    again in workers, so this is all of it)."""
    out = py(f"import sys; {WORKER_ARGV}; from nobadfind import extract; extract.init_worker(); "
             "print(sorted(m for m in ('numpy', 'nobadfind.app', 'nobadfind.embed', 'onnxruntime', 'nobadfind.engine') "
             "if m in sys.modules))")
    assert out == "[]"


def test_the_packaged_entry_point_is_light_in_a_worker_too():
    """NobadFind.exe: every worker runs packaging/launch.py again as __mp_main__; its imports used to load the whole
    app (numpy: ~500 MB of commit per text reader on a 16-thread PC, ROADMAP §2 cause 2)."""
    launch = os.path.join(APP, "packaging", "launch.py").replace("\\", "/")
    out = py(f"import sys, runpy; {WORKER_ARGV}; runpy.run_path('{launch}', run_name='__mp_main__'); "
             "print(sorted(m for m in ('numpy', 'nobadfind.app') if m in sys.modules))")
    assert out == "[]"


@pytest.mark.skipif(sys.platform != "win32", reason="private bytes are read the Windows way")
def test_numpy_loads_with_one_blas_thread_in_the_main_process():
    """OpenBLAS reserves ~32 MB of commit per CPU thread when numpy loads (515 MB on a 16-thread PC)."""
    out = py("import os, procinfo, nobadfind, numpy; "
             "print(round(procinfo.private_bytes() / 2**20), os.environ.get('OPENBLAS_NUM_THREADS'))")
    mb, var = out.split()
    assert int(mb) < 150
    assert var == "None"              # put back: programs Find opens don't inherit it


def test_workers_keep_one_blas_thread_for_numpy_loaded_later():
    out = py(f"import sys, os; {WORKER_ARGV}; import nobadfind; "
             "print(os.environ.get('OPENBLAS_NUM_THREADS'), 'numpy' in sys.modules)")
    assert out == "1 False"


def test_the_users_own_blas_setting_is_left_alone():
    out = py("import os, nobadfind; print(os.environ.get('OPENBLAS_NUM_THREADS'))", env={"OPENBLAS_NUM_THREADS": "4"})
    assert out == "4"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows calls")
def test_eco_qos_and_trim_work_on_our_own_process():
    out = py("import procinfo; from nobadfind import winapi; a = procinfo.working_set(); "
             "t = winapi.trim_working_set(); e = winapi.eco_qos(True); "
             "print(t, e, procinfo.working_set() < a)")
    assert out == "True True True"


def test_nothing_happens_to_a_process_that_is_gone():
    from nobadfind import winapi
    assert winapi.eco_qos(True, pid=0xFFFFFFF0) is False
    assert winapi.trim_working_set(pid=0xFFFFFFF0) is False


def test_mail_parsing_loads_only_for_mail_files():
    out = py(f"import sys; {WORKER_ARGV}; from nobadfind import extract; extract.init_worker(); "
             "print(sorted(m for m in ('email', 'email.policy', 'mailbox') if m in sys.modules))")
    assert out == "[]"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows priorities")
def test_worker_priorities_are_low_without_capping_the_working_set():
    """Workers: idle CPU priority, low memory priority, very low I/O priority. Not Windows background mode: from a
    process's start it pins the working set near 32 MB, and a PDF reader then page-faults ~400x more
    (docs/measurements.md)."""
    out = py("import procinfo; from nobadfind import winapi; winapi.worker_priority(True); "
             "b = bytearray(160 * 1024 * 1024); b[::4096] = b'x' * len(b[::4096]); "
             "print(procinfo.priority_class() == procinfo.IDLE_PRIORITY_CLASS, procinfo.memory_priority(), "
             "procinfo.io_priority(), procinfo.working_set() > 128 << 20)")
    assert out == "True 2 0 True"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows priorities")
def test_worker_priority_back_to_normal():
    out = py("import procinfo; from nobadfind import winapi; winapi.worker_priority(True); "
             "winapi.worker_priority(False); "
             "print(procinfo.priority_class() == procinfo.NORMAL_PRIORITY_CLASS, procinfo.io_priority())")
    assert out == "True 2"


def test_launch_imports_the_app_only_after_freeze_support():
    """NobadFind.exe: a frozen worker runs launch.py as __main__ and freeze_support() takes over (and exits) there,
    so nothing above it may import the app. Checked on the source, since a test can't be a frozen worker."""
    import ast
    tree = ast.parse(open(os.path.join(APP, "packaging", "launch.py"), encoding="utf-8").read())

    def imports_app(node):
        return any(isinstance(n, (ast.Import, ast.ImportFrom)) and "nobadfind" in (
            getattr(n, "module", "") or "".join(a.name for a in n.names)) for n in ast.walk(node))
    top = [n for n in tree.body if not (isinstance(n, ast.If) and "__main__" in ast.unparse(n.test))]
    assert not any(imports_app(n) for n in top)
    main = next(n for n in tree.body if isinstance(n, ast.If) and "__main__" in ast.unparse(n.test))
    calls = [ast.unparse(n) for n in main.body]
    first_import = next(i for i, n in enumerate(main.body) if imports_app(n))
    assert any("freeze_support()" in c for c in calls[:first_import])


def test_numpy_is_loaded_with_one_blas_thread(tmp_path):
    """Whatever the PC's thread count: a stand-in numpy records OPENBLAS_NUM_THREADS at the moment it loads."""
    (tmp_path / "numpy.py").write_text("import os\nSEEN = os.environ.get('OPENBLAS_NUM_THREADS')\n")
    out = py("import os, sys, nobadfind, numpy; print(numpy.SEEN, os.environ.get('OPENBLAS_NUM_THREADS'))",
             env={"PYTHONPATH": f"{tmp_path}{os.pathsep}{APP}"})
    assert out == "1 None"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows jobs")
def test_eco_qos_refuses_a_process_outside_the_job():
    from nobadfind import jobs, winapi
    job = jobs.Job()
    try:
        assert winapi.eco_qos(True, pid=os.getpid(), job=job.handle) is False     # this process isn't in it
    finally:
        job.close()
