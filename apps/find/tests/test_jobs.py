import os
import subprocess
import sys

import pytest

from nobadfind import winapi

pytestmark = pytest.mark.skipif(not winapi.WIN, reason="Windows only")

# the real interpreter, not the venv launcher shim (which spawns a second process)
SLEEP = [getattr(sys, "_base_executable", sys.executable), "-c", "import time; time.sleep(60)"]


@pytest.fixture
def procs():
    started = []
    yield started
    for p in started:
        p.kill()
        p.wait(timeout=10)


def spawn(procs, args=SLEEP, **kw):
    p = subprocess.Popen(args, **kw)
    procs.append(p)
    return p


def test_closing_the_job_ends_its_processes(procs):
    from nobadfind import jobs
    job = jobs.Job()
    p = spawn(procs)
    assert job.assign(p.pid)
    job.close()
    p.wait(timeout=5)
    assert p.returncode is not None


def test_cpu_cap_can_be_set_and_removed():
    from nobadfind import jobs
    job = jobs.Job()
    try:
        assert job.set_cpu_cap(15) is True
        assert job.cpu_cap() == 15
        assert job.set_cpu_cap(None) is True
        assert job.cpu_cap() is None
    finally:
        job.close()


def test_usage_counts_processes(procs):
    from nobadfind import jobs
    job = jobs.Job()
    try:
        p = spawn(procs)
        assert job.assign(p.pid)
        u = job.usage()
        assert u["processes"] == 1
        assert set(u) == {"cpu_seconds", "read_bytes", "write_bytes", "memory_mb", "processes"}
        assert job.pids() == [p.pid]
    finally:
        job.close()


def test_process_info_reads_a_live_process():
    from nobadfind import jobs
    info = jobs.process_info(os.getpid())
    assert info["pid"] == os.getpid()
    assert info["memory_mb"] > 0 and info["cpu_seconds"] >= 0
    assert jobs.process_info(0x7FFFFFF0)["memory_mb"] == 0


def test_a_process_already_in_a_job_can_join_a_second_job(procs):
    """Nesting: workers are children of main (already in OUTER) and must still reach WORKERS."""
    from nobadfind import jobs
    outer = jobs.Job()
    inner = jobs.Job(jobs.WORKERS_PREFIX + "x-test-nest-%d" % os.getpid())
    try:
        p = spawn(procs)
        assert outer.assign(p.pid)
        assert inner.assign(p.pid)
        assert p.pid in inner.pids() and p.pid in outer.pids()
    finally:
        # detach test processes first so closing can never touch pytest
        for q in procs:
            q.kill()
        inner.close()
        outer.close()


def test_join_workers_puts_a_child_in_the_named_job(procs):
    from nobadfind import jobs
    workers = jobs.Job(jobs.WORKERS_PREFIX + str(os.getpid()))
    try:
        # the child reports its own pid: under a venv, Popen.pid can be the launcher, not the interpreter
        code = ("import os, time; from nobadfind import jobs; jobs.join_workers(); "
                "print(os.getpid(), flush=True); time.sleep(60)")
        env = dict(os.environ, NOBAD_FIND_MAIN_PID=str(os.getpid()))
        p = spawn(procs, [sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, text=True)
        child = int(p.stdout.readline())
        assert child in workers.pids()
    finally:
        for q in procs:
            q.kill()
        workers.close()


def test_join_workers_without_a_job_is_a_noop(procs):
    code = "from nobadfind import jobs; jobs.join_workers(); print('ok')"
    env = dict(os.environ, NOBAD_FIND_MAIN_PID="1999999")
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=20)
    assert out.stdout.strip() == "ok"


def _limit_flags(job):
    from nobadfind import jobs
    info = jobs._Extended()
    assert jobs._k.QueryInformationJobObject(job.handle, jobs._CLS_EXTENDED, jobs.ctypes.byref(info),
                                             jobs.ctypes.sizeof(info), None)
    return info.Basic.LimitFlags


def test_outer_job_lets_opened_files_break_away():
    """C-1: the program a file opens in must not die with NOBAD Find, so OUTER allows breakaway
    (asked for per process; never the silent kind, which would let workers escape too)."""
    from nobadfind import jobs
    job = jobs.Job(breakaway=True)
    try:
        flags = _limit_flags(job)
        assert flags & jobs._KILL_ON_JOB_CLOSE and flags & jobs._BREAKAWAY_OK
        assert not flags & 0x1000                      # JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
    finally:
        job.close()
    plain = jobs.Job()
    try:
        assert not _limit_flags(plain) & jobs._BREAKAWAY_OK      # WORKERS keeps everything inside
    finally:
        plain.close()


def test_a_breakaway_child_survives_closing_the_job(procs):
    """A process in a breakaway-OK job starts a child with CREATE_BREAKAWAY_FROM_JOB: closing the job ends
    the parent but not that child (what winapi.open_outside_job relies on)."""
    from nobadfind import jobs, winapi
    job = jobs.Job(breakaway=True)
    code = ("import subprocess, sys; sys.stdin.readline(); "
            f"c = subprocess.Popen({SLEEP!r}, creationflags={winapi.CREATE_BREAKAWAY_FROM_JOB}); "
            "print(c.pid, flush=True); sys.stdin.readline()")
    parent = spawn(procs, [SLEEP[0], "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    child = None
    try:
        assert job.assign(parent.pid)
        parent.stdin.write("go\n")
        parent.stdin.flush()
        child = int(parent.stdout.readline())
        assert child not in job.pids()
        job.close()
        parent.wait(timeout=10)
        assert jobs.process_info(child)["memory_mb"] > 0          # still running
    finally:
        job.close()
        if child:
            from nobadfind.watchdog import kill_process
            kill_process(child)                                    # the pid this test started


def test_worker_job_memory_limit_is_a_hard_backstop(procs):
    """JOB_OBJECT_LIMIT_JOB_MEMORY on the worker job: above it, allocations in the workers fail (a MemoryError the
    readers already handle) instead of the PC paging. Close-with-app stays on."""
    from nobadfind import jobs
    job = jobs.Job()
    try:
        assert job.set_memory_limit(512)
        info = jobs._Extended()
        jobs._k.QueryInformationJobObject(job.handle, jobs._CLS_EXTENDED, jobs.ctypes.byref(info),
                                          jobs.ctypes.sizeof(info), None)
        assert info.Basic.LimitFlags & jobs._JOB_MEMORY and info.Basic.LimitFlags & jobs._KILL_ON_JOB_CLOSE
        assert info.JobMemoryLimit == 512 * 1024 * 1024
        p = spawn(procs, [getattr(sys, "_base_executable", sys.executable), "-c",
                          "import sys; sys.stdin.readline(); b = bytearray(700 * 1024 * 1024)"],
                  stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        assert job.assign(p.pid)
        p.stdin.write(b"go\n")
        p.stdin.close()
        p.wait(timeout=60)
        assert p.returncode != 0 and b"MemoryError" in p.stderr.read()
    finally:
        job.close()


def test_worker_memory_limit_follows_the_pc():
    from nobadfind import jobs
    assert jobs.worker_memory_limit_mb(16 * 1024) == 4096
    assert jobs.worker_memory_limit_mb(8 * 1024) == 2048
    assert jobs.worker_memory_limit_mb(2 * 1024) == 1024
    assert jobs.worker_memory_limit_mb(64 * 1024) == 4096
