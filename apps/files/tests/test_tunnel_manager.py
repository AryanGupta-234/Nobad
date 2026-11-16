from __future__ import annotations

import asyncio
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from core.result import OperationStatus
from core.tunnel_manager import (
    DEFAULT_TUNNEL_PRESETS,
    SSHTunnelManager,
    TunnelConfig,
    TunnelSessionInfo,
    TunnelStatus,
    TunnelType,
)


class TestTunnelManager(TestCase):
    def test_tunnel_config_serialization(self) -> None:
        cfg = TunnelConfig(
            id="t1",
            name="Test PostgreSQL",
            tunnel_type=TunnelType.LOCAL,
            local_host="127.0.0.1",
            local_port=5433,
            remote_host="10.0.0.5",
            remote_port=5432,
            auto_connect=True,
            description="Test DB",
            category="database",
        )
        d = cfg.to_dict()
        self.assertEqual(d["id"], "t1")
        self.assertEqual(d["tunnel_type"], "local")
        self.assertEqual(d["local_port"], 5433)
        self.assertEqual(d["remote_port"], 5432)

        restored = TunnelConfig.from_dict(d)
        self.assertEqual(restored.id, "t1")
        self.assertEqual(restored.tunnel_type, TunnelType.LOCAL)
        self.assertEqual(restored.local_port, 5433)
        self.assertEqual(restored.remote_host, "10.0.0.5")
        self.assertTrue(restored.auto_connect)

    def test_generate_openssh_command_local(self) -> None:
        cfg = TunnelConfig(
            tunnel_type=TunnelType.LOCAL,
            local_host="127.0.0.1",
            local_port=5433,
            remote_host="127.0.0.1",
            remote_port=5432,
        )
        cmd = SSHTunnelManager.generate_openssh_command(
            cfg, host="db.server.internal", username="deploy", port=2222
        )
        self.assertIn("ssh -N -L 127.0.0.1:5433:127.0.0.1:5432", cmd)
        self.assertIn("deploy@db.server.internal", cmd)
        self.assertIn("-p 2222", cmd)

    def test_generate_openssh_command_remote(self) -> None:
        cfg = TunnelConfig(
            tunnel_type=TunnelType.REMOTE,
            local_host="127.0.0.1",
            local_port=3000,
            remote_host="0.0.0.0",
            remote_port=8080,
        )
        cmd = SSHTunnelManager.generate_openssh_command(
            cfg, host="web.server.com", username="root"
        )
        self.assertIn("ssh -N -R 0.0.0.0:8080:127.0.0.1:3000", cmd)
        self.assertIn("root@web.server.com", cmd)

    def test_generate_openssh_command_socks5(self) -> None:
        cfg = TunnelConfig(
            tunnel_type=TunnelType.DYNAMIC_SOCKS5,
            local_host="127.0.0.1",
            local_port=1080,
        )
        cmd = SSHTunnelManager.generate_openssh_command(
            cfg, host="proxy.node.com", username="ubuntu"
        )
        self.assertIn("ssh -N -D 127.0.0.1:1080", cmd)
        self.assertIn("ubuntu@proxy.node.com", cmd)

    def test_default_presets_valid(self) -> None:
        self.assertGreaterEqual(len(DEFAULT_TUNNEL_PRESETS), 5)
        for p in DEFAULT_TUNNEL_PRESETS:
            self.assertIn("name", p)
            self.assertIn("local_port", p)
            self.assertIn("tunnel_type", p)


class TestTunnelAsyncOperations(IsolatedAsyncioTestCase):
    async def test_start_and_stop_local_tunnel(self) -> None:
        mgr = SSHTunnelManager()

        mock_listener = MagicMock()
        mock_listener.close = MagicMock()
        mock_listener.wait_closed = AsyncMock()

        mock_conn = MagicMock()
        mock_conn.forward_local_port = AsyncMock(return_value=mock_listener)

        cfg = TunnelConfig(
            id="t-local",
            name="Mock Local Forward",
            tunnel_type=TunnelType.LOCAL,
            local_host="127.0.0.1",
            local_port=49152,  # high unassigned ephemeral port
            remote_host="127.0.0.1",
            remote_port=5432,
        )

        # Mock port in use check to return False
        with patch.object(SSHTunnelManager, "is_port_in_use", return_value=False):
            with patch.object(SSHTunnelManager, "test_socket_ping", return_value=(True, 15.2, "Reachable")):
                res = await mgr.start_tunnel(mock_conn, cfg)

        self.assertEqual(res.status, OperationStatus.SUCCESS)
        mock_conn.forward_local_port.assert_awaited_once_with("127.0.0.1", 49152, "127.0.0.1", 5432)

        session = mgr.get_session("t-local")
        self.assertIsNotNone(session)
        self.assertEqual(session.status, TunnelStatus.ACTIVE)
        self.assertEqual(session.latency_ms, 15.2)

        # Stop tunnel
        stop_res = await mgr.stop_tunnel("t-local")
        self.assertEqual(stop_res.status, OperationStatus.SUCCESS)
        mock_listener.close.assert_called_once()
        mock_listener.wait_closed.assert_awaited_once()
        self.assertEqual(session.status, TunnelStatus.INACTIVE)

    async def test_start_socks5_tunnel(self) -> None:
        mgr = SSHTunnelManager()

        mock_listener = MagicMock()
        mock_listener.close = MagicMock()
        mock_listener.wait_closed = AsyncMock()

        mock_conn = MagicMock()
        mock_conn.forward_socks = AsyncMock(return_value=mock_listener)

        cfg = TunnelConfig(
            id="t-socks",
            name="Mock SOCKS5",
            tunnel_type=TunnelType.DYNAMIC_SOCKS5,
            local_host="127.0.0.1",
            local_port=49153,
        )

        with patch.object(SSHTunnelManager, "is_port_in_use", return_value=False):
            res = await mgr.start_tunnel(mock_conn, cfg)

        self.assertEqual(res.status, OperationStatus.SUCCESS)
        mock_conn.forward_socks.assert_awaited_once_with("127.0.0.1", 49153)

        session = mgr.get_session("t-socks")
        self.assertEqual(session.status, TunnelStatus.ACTIVE)

        # Stop all
        await mgr.stop_all_tunnels()
        self.assertEqual(session.status, TunnelStatus.INACTIVE)

    async def test_port_collision_prevents_listener_failure(self) -> None:
        mgr = SSHTunnelManager()
        mock_conn = MagicMock()

        cfg = TunnelConfig(
            id="t-collide",
            name="Colliding Tunnel",
            tunnel_type=TunnelType.LOCAL,
            local_port=80,
        )

        with patch.object(SSHTunnelManager, "is_port_in_use", return_value=True):
            res = await mgr.start_tunnel(mock_conn, cfg)

        self.assertEqual(res.status, OperationStatus.FAILED)
        self.assertIn("Port collision", res.message)

    async def test_start_remote_tunnel(self) -> None:
        mgr = SSHTunnelManager()

        mock_listener = MagicMock()
        mock_listener.close = MagicMock()
        mock_listener.wait_closed = AsyncMock()

        mock_conn = MagicMock()
        mock_conn.forward_remote_port = AsyncMock(return_value=mock_listener)

        cfg = TunnelConfig(
            id="t-remote",
            name="Mock Remote Forward",
            tunnel_type=TunnelType.REMOTE,
            local_host="127.0.0.1",
            local_port=3000,
            remote_host="0.0.0.0",
            remote_port=8080,
        )

        res = await mgr.start_tunnel(mock_conn, cfg)
        self.assertEqual(res.status, OperationStatus.SUCCESS)
        mock_conn.forward_remote_port.assert_awaited_once_with("0.0.0.0", 8080, "127.0.0.1", 3000)

        session = mgr.get_session("t-remote")
        self.assertEqual(session.status, TunnelStatus.ACTIVE)

    async def test_start_tunnel_reentrant_returns_success(self) -> None:
        mgr = SSHTunnelManager()

        mock_listener = MagicMock()
        mock_conn = MagicMock()
        mock_conn.forward_local_port = AsyncMock(return_value=mock_listener)

        cfg = TunnelConfig(
            id="t-reentrant",
            name="Reentrant Tunnel",
            tunnel_type=TunnelType.LOCAL,
            local_port=49154,
        )

        with patch.object(SSHTunnelManager, "is_port_in_use", return_value=False):
            res1 = await mgr.start_tunnel(mock_conn, cfg)
            self.assertEqual(res1.status, OperationStatus.SUCCESS)

            # Re-entrant start on active session should return success immediately
            res2 = await mgr.start_tunnel(mock_conn, cfg)
            self.assertEqual(res2.status, OperationStatus.SUCCESS)
            self.assertIn("already active", res2.message)

    async def test_non_ssh_connection_rejected(self) -> None:
        mgr = SSHTunnelManager()
        ftp_mock = MagicMock(spec=["upload_file", "download_file"])  # lacks forward_local_port

        cfg = TunnelConfig(id="t-ftp", name="FTP Tunnel", tunnel_type=TunnelType.LOCAL)
        res = await mgr.start_tunnel(ftp_mock, cfg)
        self.assertEqual(res.status, OperationStatus.FAILED)
        self.assertIn("does not support SSH port forwarding", res.message)

    async def test_acm_wrapper_awaitable_listener(self) -> None:
        mgr = SSHTunnelManager()

        class MockListener:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

            async def wait_closed(self):
                pass

        real_listener = MockListener()

        # Simulate asyncssh _ACMWrapper which implements __await__ but is not asyncio.iscoroutine
        class MockACMWrapper:
            def __init__(self, target):
                self._target = target

            def __await__(self):
                async def _inner():
                    return self._target
                return _inner().__await__()

        wrapper = MockACMWrapper(real_listener)
        mock_conn = MagicMock()
        mock_conn.forward_local_port = MagicMock(return_value=wrapper)

        cfg = TunnelConfig(id="t-acm", name="ACM Tunnel", tunnel_type=TunnelType.LOCAL, local_port=49155)

        with patch.object(SSHTunnelManager, "is_port_in_use", return_value=False):
            start_res = await mgr.start_tunnel(mock_conn, cfg)
            self.assertEqual(start_res.status, OperationStatus.SUCCESS)

            # Session listener must be unwrapped into real listener with close()
            session = mgr.get_session("t-acm")
            self.assertIs(session.listener, real_listener)

            stop_res = await mgr.stop_tunnel("t-acm")
            self.assertEqual(stop_res.status, OperationStatus.SUCCESS)
            self.assertTrue(real_listener.closed)
