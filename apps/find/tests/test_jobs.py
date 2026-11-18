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
