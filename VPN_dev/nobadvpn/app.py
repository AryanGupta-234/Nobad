"""Application wiring and entry point."""
import argparse
import atexit
import os
import sys
import threading

from . import autostart, lifecycle, recovery, watchdog   # light: also used by --panic / --watchdog / --version
from .const import (APP_VER, LEGACY_DATA_DIR, LEGACY_SETTINGS_PATH, LOG_DIR, SESS_PATH, SETTINGS_PATH, SMART_PATH,
                    USAGE_PATH, DATA_DIR)
from .ctx import ctx
from .logbus import init_file_logging, log
from .syscmd import is_admin, spawn, try_self_elevate


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="NobadVPN", add_help=True)
    p.add_argument("--background", action="store_true", help="start hidden in the tray")
    p.add_argument("--watchdog", type=int, metavar="PID", help=argparse.SUPPRESS)
    p.add_argument("--panic", action="store_true",
                   help="restore internet: remove NOBAD firewall rules, tunnel services and DNS changes, then exit")
    p.add_argument("--repair-network", choices=("quick", "full"),
                   help="restore internet, then repair Windows networking (full = Winsock/TCP-IP reset, needs restart)")
    p.add_argument("--show-result", action="store_true", help=argparse.SUPPRESS)  # Start-menu shortcut: message box
    p.add_argument("--guard", action="store_true", help=argparse.SUPPRESS)        # boot guard task (SYSTEM)
    p.add_argument("--selftest", action="store_true", help="print what this machine supports")
    p.add_argument("--version", action="store_true")
    p.add_argument("--install-tasks", action="store_true", help=argparse.SUPPRESS)  # run by the installer (elevated)
    p.add_argument("--autostart", choices=("on", "off"), help=argparse.SUPPRESS)
    args, _unknown = p.parse_known_args(argv)
    return args


def init(headless_test=False):
    """Create every singleton. Safe to call once per process (tests call it with a temp NOBAD_DATA_DIR)."""
    from .engine import Tunnel, ensure_dirs
    from .netwatch import NetWatch
    from .settings import Settings
    from .smart import Smart
    from .tray import Tray
    from .updater import Updater
    from .usage import Usage
    migrated = migrate_legacy_data()
    os.makedirs(DATA_DIR, exist_ok=True)
    init_file_logging(LOG_DIR)
    if migrated:
        log(f"copied settings, configs and history from {LEGACY_DATA_DIR} (NOMAD Tunnel) to {DATA_DIR}", "info")
    ctx.settings = Settings(SETTINGS_PATH, LEGACY_SETTINGS_PATH)
    if ctx.settings.migrated_from:
        log(f"settings moved to {SETTINGS_PATH}", "info")
    ensure_dirs()
    ctx.usage = Usage(USAGE_PATH, SESS_PATH)
    ctx.smart = Smart(SMART_PATH)
    ctx.updater = Updater()
    ctx.tray = Tray()
    ctx.tunnel = Tunnel()
    ctx.netwatch = NetWatch(ctx.tunnel, ctx.settings)
    from .netintel.agent import FixAgent
    from .notify import notify
    ctx.niagent = FixAgent(ctx.settings, ctx.tunnel, notify=notify)
    ctx.netwatch.listeners.append(ctx.niagent.on_network_change)
    from . import reach
    ctx.netwatch.listeners.append(lambda *a, **k: reach.forget())   # new network: re-learn which routes work
    if extra_hook not in ctx.state_hooks:
        ctx.state_hooks.append(extra_hook)
    return ctx


def migrate_legacy_data():
    """First start after the rename: copy the old ProgramData folder (configs, settings, usage, smart data).
    The old folder is left in place; DPAPI machine-scope blobs stay valid because only the path changes."""
    import shutil
    if not LEGACY_DATA_DIR or not os.path.isdir(LEGACY_DATA_DIR) or os.path.exists(SETTINGS_PATH):
        return False
    try:
        shutil.copytree(LEGACY_DATA_DIR, DATA_DIR, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("runtime", "logs", "updates", "instance.json", "*.tmp",
                                                      "clean_exit.flag"))
        return True
    except (OSError, shutil.Error):
        return False


def _legacy_cleanup():
    """Old NOMAD Tunnel firewall rules and startup task — only when no old tunnel is still relying on them."""
    from . import firewall
    try:
        old = firewall.legacy_present()
        if old:
            firewall.remove(old)
            log(f"removed {len(old)} firewall rule(s) left by NOMAD Tunnel", "info")
        if autostart.remove_legacy_task():
            log("removed NOMAD Tunnel's startup task", "info")
    except Exception as e:
        log(f"legacy cleanup failed: {e}", "warn")


def extra_hook():
    from . import api   # heavy (urllib/ssl, every handler): only the UI process needs it
    return api.extra_state()


def _repair_autostart():
    """If 'Start with Windows' points at an old install location, point it at this one."""
    try:
        if ctx.settings.get("start_with_windows") and autostart.task_exists() and not autostart.task_matches():
            ok, msg = autostart.enable()
            log("start-with-Windows task updated for this install" if ok else f"couldn't update the startup task: {msg}",
                "info" if ok else "warn")
    except Exception as e:
        log(f"startup task check failed: {e}", "warn")


def _background_start(tunnel):
    """Everything that talks to netsh / schtasks / PowerShell runs here, AFTER the window is on screen."""
    from . import splash
    try:
        w = ctx.windows
        if w is not None and w.revealed_event.wait(12):   # let the window paint its first frames undisturbed
            ctx.quit_event.wait(1.5)
        _legacy_cleanup()          # old NOMAD rules first, so they can never trap the user offline
        tunnel.start()             # adopt a running tunnel / keep or clear rules, then the monitor loops
        s = ctx.settings
        from . import api
        api.auto_install_wireguard()   # WireGuard removed since install? put it back (signed copy, background)
        if s.get("auto_connect") and s.get("last_region") and not tunnel.connected and not tunnel.connecting:
            tunnel.connect(s.get("last_region"))
        from . import api
        api.refresh_autostart_cache()
        tunnel.push()
        _repair_autostart()
        if autostart.ensure_launcher_task():
            log("no-UAC launcher task is in place", "info")
        if autostart.ensure_guard_task():
            log("boot guard is in place (restores internet if NOBAD ever dies with the kill switch on)", "info")
        if ctx.niagent:
            ctx.niagent.start()    # sleeps 30 min between scans; a scan does nothing unless the agent is switched on
        if s.get("watchdog") and not ctx.quit_event.wait(3):
            watchdog.spawn_watchdog()
        from . import crash
        crash.auto_send_if_opted_in()
        if s.get("auto_update_check") and s.get("update_url"):
            ctx.updater.check()
    except Exception as e:
        log(f"background start-up step failed: {e}", "warn")
    finally:
        ctx.started.set()
        if ctx.windows is None or ctx.windows.main is None:
            splash.close()


def install_tasks(autostart_mode=None):
    """Called by the installer (already elevated, as the installing user): register the no-UAC launcher task and,
    if chosen, 'Start with Windows'. No window, no engine. Exit code 0 on success."""
    if os.name == "nt" and not is_admin():
        return 2
    from .settings import Settings
    os.makedirs(DATA_DIR, exist_ok=True)
    ok = True
    if autostart.installed_location():
        ok = autostart.ensure_launcher_task() and ok
        ok = autostart.ensure_guard_task() and ok
    if autostart_mode:
        s = Settings(SETTINGS_PATH, LEGACY_SETTINGS_PATH)
        if autostart_mode == "on":
            done, _msg = autostart.enable()
        else:
            done, _msg = autostart.disable()
        ok = done and ok
        s.set("start_with_windows", bool(done and autostart_mode == "on"))
    return 0 if ok else 1


def _cli_repair(args):
    """`--panic` (Start-menu "Restore internet", uninstaller) and `--repair-network`: no window, works offline.
    If NOBAD is running, the running engine does the work (so auto-repair can't fight the reset); otherwise it is
    done right here without starting the engine."""
    from . import netrepair
    level = args.repair_network or "undo"
    if os.name == "nt" and not is_admin():
        if args.show_result:
            _message_box("NOBAD VPN", "Administrator rights are needed to change network settings.", ok=False)
        return 1
    os.makedirs(DATA_DIR, exist_ok=True)
    inst = lifecycle.read_instance() or {}
    if _instance_alive() and inst.get("port") and inst.get("token"):
        try:
            r = lifecycle._post_local(inst["port"], inst["token"], "/api/net_repair", {"level": level}, 5)
            if r.get("ok"):
                msg = "NOBAD is running, so it is doing this itself. Results appear in the app."
                print(msg)
                if args.show_result:
                    _message_box("NOBAD VPN", msg)
                return 0
        except Exception:
            pass   # not answering: do it here
    res = netrepair.repair(level)
    lines = [("OK   " if s["ok"] else "FAIL ") + s["step"] + (f" - {s['detail']}" if s["detail"] else "") for s in res["steps"]]
    text = "\n".join(lines)
    print(text)
    if args.show_result:
        _message_box("NOBAD VPN - " + ("Internet restored" if res["ok"] else "Finished with problems"),
                     text + ("\n\nRestart Windows to finish the network reset." if res["restart_needed"] else ""),
                     ok=res["ok"])
    return 0 if res["ok"] else 1


def _instance_alive():
    from .watchdog import _pid_alive
    inst = lifecycle.read_instance() or {}
    try:
        return _pid_alive(int(inst.get("pid") or 0))
    except (TypeError, ValueError):
        return False


def _message_box(title, text, ok=True):
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40 if ok else 0x30)   # info / warning icon
    except Exception:
        pass


def _run_main_process(args):
    from . import splash
    from .server import TOKEN, make_server
    from .window import WindowManager, set_dpi_awareness
    want_window = (not args.background) or autostart.consume_show_flag()
    if lifecycle.handoff_to_running(show=want_window):
        splash.close()
        return  # an existing NOBAD brought its window forward: nothing else to do
    lifecycle.kill_other_instances()
    lifecycle.mark_started()
    from . import crash
    crash.install_hooks()
    init()
    srv = make_server()
    port = srv.server_address[1]
    lifecycle.write_instance(port, TOKEN)
    atexit.register(lifecycle.remove_instance)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    tunnel = ctx.tunnel
    ctx.netwatch.start()
    if ctx.settings.get("tray"):
        ctx.tray.start()
    tray_ok = ctx.tray.icon is not None
    show = want_window or not tray_ok
    if not show:
        splash.close()
    url = f"http://127.0.0.1:{port}"
    set_dpi_awareness()
    wm = WindowManager(url)
    ctx.windows = wm
    spawn(_background_start, tunnel)
    clean = False
    try:
        if wm.create(start_hidden=not show, on_shown=splash.close):
            wm.run()
        else:
            import webbrowser
            splash.close()
            wm.revealed_event.set()   # no native window: background start-up need not wait
            if show:
                from .server import launch_url
                webbrowser.open(launch_url(url, "/"))
                print(f"pywebview not installed — opened {url} in your browser. (pip install pywebview for the native window)")
            ctx.quit_event.wait()
        if not ctx.quit_event.is_set() and ctx.settings.get("guardian") and (tunnel.connected or tunnel.want):
            log("window closed — guarding in the background", "info")
            ctx.quit_event.wait()
        clean = True
    except KeyboardInterrupt:
        clean = True
    finally:
        splash.close()
        for step in (wm.save_state, ctx.netwatch.stop, tunnel.flush_usage, tunnel.stop, ctx.tray.stop,
                     lifecycle.remove_instance):
            try:
                step()
            except Exception as e:  # never let one failing step skip the rest
                log(f"shutdown step {getattr(step, '__name__', step)} failed: {e}", "warn")
        if clean:
            lifecycle.mark_clean_exit()  # tells the watchdog (and the next start) this was a normal exit


def main(argv=None):
    args = parse_args(argv)
    if args.version:
        print(APP_VER)
        return 0
    if args.watchdog:
        return watchdog.run_watchdog(args.watchdog)
    if args.selftest:
        from .selftest import run_selftest
        return run_selftest()
    if args.install_tasks:
        return install_tasks(args.autostart)
    if args.guard:
        if os.name == "nt" and not is_admin():
            return 2          # only the SYSTEM task runs this
        os.makedirs(DATA_DIR, exist_ok=True)
        recovery.boot_guard()
        return 0
    cli_fix = args.panic or args.repair_network
    if os.name == "nt" and not is_admin():
        if not cli_fix and autostart.launch_via_task(show_window=not args.background):
            return 0  # the elevated scheduled task takes over: no UAC prompt
        if try_self_elevate():
            return 0
    if cli_fix:
        return _cli_repair(args)
    _run_main_process(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
