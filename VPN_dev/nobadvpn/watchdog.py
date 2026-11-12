"""Crash-proof kill switch: a tiny second process that watches the main app.

If the app dies WITHOUT writing the clean-exit marker, the watchdog looks at what's left behind:
  * tunnel still running            -> you're still protected; relaunch the app to restore monitoring
  * rules present, tunnel gone      -> you'd be offline; relaunch the app (3 tries), then either stay blocked
                                       (default, true to a kill switch) or fail open if the user chose that
  * nothing left behind             -> nothing to do
"""
import json
import os
import subprocess
import time

from . import firewall, recovery
from .const import CLEAN_EXIT_PATH, INSTANCE_PATH, SETTINGS_PATH
from .notify import toast
from .syscmd import entry_command, service_running

MAX_ATTEMPTS = 3


def decide(clean_exit, rules_present, tunnel_running, attempts, failopen):
    if clean_exit:
        return "exit"
    if tunnel_running:
        return "relaunch" if attempts < MAX_ATTEMPTS else "exit"
    if rules_present:
        if attempts < MAX_ATTEMPTS:
            return "relaunch"
        return "failopen" if failopen else "stay_blocked"
    return "exit"


def spawn_watchdog():
    flags = 0
    if os.name == "nt":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        subprocess.Popen(entry_command(["--watchdog", str(os.getpid())]), creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def _pid_alive(pid):
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not h:
            return False
        r = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
        ctypes.windll.kernel32.CloseHandle(h)
        return r == 0x102  # WAIT_TIMEOUT -> still running
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def wait_for_exit(pid, poll=1.0):
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if h:
            ctypes.windll.kernel32.WaitForSingleObject(h, 0xFFFFFFFF)
            ctypes.windll.kernel32.CloseHandle(h)
            return
    while _pid_alive(pid):
        time.sleep(poll)


def _failopen_setting():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return bool(json.load(f).get("watchdog_failopen"))
    except Exception:
        return False


def _relaunch_and_wait(parent_pid):
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    t0 = time.time()
    try:
        subprocess.Popen(entry_command(["--background"]), creationflags=flags, close_fds=True)
    except OSError:
        return False
    while time.time() - t0 < 45:
        time.sleep(2)
        try:
            with open(INSTANCE_PATH, "r") as f:
                inst = json.load(f)
            if inst.get("pid") != parent_pid and inst.get("ts", 0) >= t0 - 1 and _pid_alive(int(inst["pid"])):
                return True
        except Exception:
            pass
    return False


def run_watchdog(parent_pid):
    wait_for_exit(parent_pid)
    time.sleep(1.0)
    attempts = 0
    while True:
        clean = os.path.exists(CLEAN_EXIT_PATH)
        running = any(service_running(n) for n in recovery.config_names())
        rules = bool(firewall.present())
        action = decide(clean, rules, running, attempts, _failopen_setting())
        if action == "exit":
            return 0
        if action == "relaunch":
            attempts += 1
            if _relaunch_and_wait(parent_pid):
                return 0  # the new instance starts its own watchdog
            time.sleep(5)
            continue
        if action == "failopen":
            recovery.panic_reset_system(restore_dns=True)
            toast("NOBAD stopped", "The kill switch was released so you are not left offline.")
            return 0
        toast("NOBAD stopped — internet is blocked",
              "The kill switch is still active. Open NOBAD, or use \"Restore internet (NOBAD)\" in the Start menu.")
        return 0
