"""Editor tabs: server files (real AsyncSSH SFTP server) and local files, the "changed since you opened it" check,
compare/reload, and Monaco bundled locally with no CDN anywhere (issue #30)."""
from __future__ import annotations

import asyncio
import http.client
import json
import os
import queue
import re
import time
from pathlib import Path

import pytest

asyncssh = pytest.importorskip("asyncssh")

from app_web import bus  # noqa: E402
from app_web.api import api_post  # noqa: E402
from app_web.context import AppContext  # noqa: E402
from app_web.handlers import register_all  # noqa: E402
from app_web.server import COOKIE, CSP, MONACO_DIR, BridgeServer  # noqa: E402
from core.async_runtime import AsyncRuntime  # noqa: E402

register_all()
USER, PASSWORD = "deploy", "s3cret-pass"
APP_ROOT = Path(__file__).resolve().parents[1]


class _Server(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == USER and password == PASSWORD


def _close_on_loop(server) -> None:  # type: ignore[no-untyped-def]
    async def close() -> None:
        server.close()
        try:                                  # wait_closed also waits for open client connections
            await asyncio.wait_for(server.wait_closed(), 2)
        except asyncio.TimeoutError:
            pass

    AsyncRuntime.instance().run(close())


@pytest.fixture
def remote_root(tmp_path: Path):
    root = tmp_path / "srv"
    (root / "site").mkdir(parents=True)
    (root / "site" / "config.php").write_text("<?php\nreturn ['debug' => false];\n", encoding="utf-8")
    (root / "site" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4)

    async def start():
        key = asyncssh.generate_private_key("ssh-ed25519")
        srv = await asyncssh.create_server(_Server, "127.0.0.1", 0, server_host_keys=[key],
                                           sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=str(root)))
        return srv, srv.sockets[0].getsockname()[1]

    srv, port = AsyncRuntime.instance().run(start())
    yield root, port
    _close_on_loop(srv)


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    context = AppContext.create(tmp_path / "app.sqlite3")
    yield context
    context.session.disconnect()
    context.editor.shutdown()


def _connect(ctx: AppContext, port: int) -> None:
    q = bus.subscribe(500)
    try:
        assert api_post("conn.connect", {"profile": {"protocol": "sftp", "host": "127.0.0.1", "port": port, "username": USER},
                                         "secret": PASSWORD}, ctx)["ok"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                msg = json.loads(q.get(timeout=0.5))
            except queue.Empty:
                continue
            if msg["type"] == "hostkey":
                api_post("conn.trust", {"token": msg["payload"]["token"], "accept": True}, ctx)
            if msg["type"] == "connection" and msg["payload"]["status"] == "connected":
                return
        raise AssertionError("not connected")
    finally:
        bus.unsubscribe(q)


def _bump_mtime(path: Path) -> None:
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 10))


def test_server_file_open_save_and_conflict(remote_root, ctx) -> None:
    root, port = remote_root
    _connect(ctx, port)
    opened = api_post("edit.open", {"side": "remote", "path": "/site/config.php"}, ctx)
    assert opened["ok"], opened
    tab = opened["data"]
    assert tab["language"] == "php" and "'debug' => false" in tab["text"]

    saved = api_post("edit.save", {"id": tab["id"], "text": "<?php\nreturn ['debug' => true];\n"}, ctx)["data"]
    assert saved["saved"] is True
    assert "'debug' => true" in (root / "site" / "config.php").read_text(encoding="utf-8")

    # someone else changes it on the server: saving is refused, compare shows theirs, overwrite is explicit
    (root / "site" / "config.php").write_text("<?php\nreturn ['debug' => true, 'cache' => 600];\n", encoding="utf-8")
    _bump_mtime(root / "site" / "config.php")
    refused = api_post("edit.save", {"id": tab["id"], "text": "<?php\nreturn ['debug' => 'mine'];\n"}, ctx)["data"]
    assert refused["saved"] is False and refused["conflict"] is True
    assert "'cache' => 600" in (root / "site" / "config.php").read_text(encoding="utf-8")
    assert "'cache' => 600" in api_post("edit.latest", {"id": tab["id"]}, ctx)["data"]["text"]

    forced = api_post("edit.save", {"id": tab["id"], "text": "<?php\nreturn ['debug' => 'mine'];\n", "force": True}, ctx)["data"]
    assert forced["saved"] is True
    assert "'mine'" in (root / "site" / "config.php").read_text(encoding="utf-8")


def test_reload_takes_the_server_version_as_the_new_start(remote_root, ctx) -> None:
    root, port = remote_root
    _connect(ctx, port)
    tab = api_post("edit.open", {"side": "remote", "path": "/site/config.php"}, ctx)["data"]
    (root / "site" / "config.php").write_text("<?php // theirs\n", encoding="utf-8")
    _bump_mtime(root / "site" / "config.php")
    assert api_post("edit.reload", {"id": tab["id"]}, ctx)["data"]["text"] == "<?php // theirs\n"
    assert api_post("edit.save", {"id": tab["id"], "text": "<?php // mine on top of theirs\n"}, ctx)["data"]["saved"] is True


def test_binary_server_files_are_refused_and_tabs_survive_a_disconnect(remote_root, ctx) -> None:
    _root, port = remote_root
    _connect(ctx, port)
    refused = api_post("edit.open", {"side": "remote", "path": "/site/logo.png"}, ctx)
    assert not refused["ok"] and "binary" in refused["error"]

    tab = api_post("edit.open", {"side": "remote", "path": "/site/config.php"}, ctx)["data"]
    api_post("conn.disconnect", {}, ctx)
    assert [t["id"] for t in api_post("edit.list", {}, ctx)["data"]] == [tab["id"]]     # nothing is lost
    blocked = api_post("edit.save", {"id": tab["id"], "text": "x"}, ctx)
    assert not blocked["ok"] and "Connect to the server" in blocked["error"]


def test_local_file_save_is_atomic_and_detects_outside_changes(ctx, tmp_path: Path) -> None:
    target = tmp_path / "deploy.sh"
    target.write_text("#!/bin/sh\necho one\n", encoding="utf-8")
    tab = api_post("edit.open", {"side": "local", "path": str(target)}, ctx)["data"]
    assert tab["language"] in {"shell", "shellscript", "bash"}

    assert api_post("edit.save", {"id": tab["id"], "text": "#!/bin/sh\necho two\n"}, ctx)["data"]["saved"] is True
    assert target.read_text(encoding="utf-8") == "#!/bin/sh\necho two\n"
    assert not list(tmp_path.glob("*.nbfb-save"))                  # no temp file left behind

    target.write_text("#!/bin/sh\necho edited elsewhere\n", encoding="utf-8")
    _bump_mtime(target)
    refused = api_post("edit.save", {"id": tab["id"], "text": "#!/bin/sh\necho three\n"}, ctx)["data"]
    assert refused["saved"] is False and refused["conflict"] is True
    assert "edited elsewhere" in target.read_text(encoding="utf-8")


def test_opening_the_same_file_twice_reuses_the_tab(ctx, tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("# hi\n", encoding="utf-8")
    first = api_post("edit.open", {"side": "local", "path": str(target)}, ctx)["data"]
    second = api_post("edit.open", {"side": "local", "path": str(target)}, ctx)["data"]
    assert first["id"] == second["id"] and second.get("reused") is True


def test_local_binary_files_are_refused(ctx, tmp_path: Path) -> None:
    blob = tmp_path / "image.bin"
    blob.write_bytes(bytes(range(256)) * 8)
    reply = api_post("edit.open", {"side": "local", "path": str(blob)}, ctx)
    assert not reply["ok"] and "binary" in reply["error"]


# ---------------------------------------------------------------- Monaco is bundled (issue #30)
def test_no_editor_page_loads_anything_from_a_cdn() -> None:
    pages = [APP_ROOT / "app_web" / "ui" / "index.html", APP_ROOT / "app_web" / "ui" / "screens" / "editor.js"]
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert not re.search(r"https?://(unpkg\.com|cdnjs\.|cdn\.jsdelivr|fonts\.googleapis)", text), page.name


def test_bundled_monaco_is_complete_and_served_with_a_strict_csp(tmp_path: Path) -> None:
    for rel in ("vs/loader.js", "vs/editor/editor.main.js", "vs/editor/editor.main.css", "LICENSE", "VERSION.txt"):
        assert (MONACO_DIR / rel).is_file(), rel
    worker_refs = re.findall(r'"\.\./(assets/[A-Za-z0-9._-]+\.js)"', (MONACO_DIR / "vs/editor/editor.main.js").read_text(encoding="utf-8"))
    assert worker_refs and all((MONACO_DIR / "vs" / ref).is_file() for ref in worker_refs)

    assert "worker-src 'self' blob:" in CSP and "unsafe-eval" not in CSP and "script-src 'self';" in CSP
    srv = BridgeServer(AppContext.create(tmp_path / "app.sqlite3"))
    srv.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        conn.request("GET", "/static/vendor/monaco/vs/loader.js", headers={"Host": f"127.0.0.1:{srv.server_address[1]}"})
        res = conn.getresponse()
        assert res.status == 200 and res.getheader("Content-Type").startswith("text/javascript")
        res.read()
        conn.request("GET", "/static/vendor/monaco/VERSION.txt", headers={"Host": f"127.0.0.1:{srv.server_address[1]}", "Cookie": f"{COOKIE}=x"})
        assert conn.getresponse().status == 404                    # only allowed file types are served
    finally:
        srv.stop()
