from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from core.log_streamer import (
    LogEntry,
    LogSourceType,
    LogStreamConfig,
    LogStreamManager,
    LogStreamSession,
    LogStreamStatus,
    detect_log_level,
    parse_log_line,
)


class TestLogStreamerCore(unittest.TestCase):
    def test_detect_log_level(self) -> None:
        self.assertEqual(detect_log_level("Connection failed", 502), "error")
        self.assertEqual(detect_log_level("Resource not found", 404), "warn")
        self.assertEqual(detect_log_level("Login successful", 200), "success")
        self.assertEqual(detect_log_level("Redirecting", 301), "info")
        self.assertEqual(detect_log_level("CRITICAL: Out of memory"), "error")
        self.assertEqual(detect_log_level("FATAL: Worker died"), "error")
        self.assertEqual(detect_log_level("WARN: Slow query detected"), "warn")
        self.assertEqual(detect_log_level("DEBUG: Payload dump"), "debug")
        self.assertEqual(detect_log_level("INFO: Server started"), "info")
        self.assertEqual(detect_log_level("Just a plain line"), "default")

    def test_parse_access_log_line(self) -> None:
        raw = '172.68.21.4 - - [29/Oct/2026:15:42:01 +0000] "POST /api/v1/checkout HTTP/1.1" 200 4820 18.4ms'
        entry = parse_log_line(raw, "Nginx Access", 1)
        self.assertEqual(entry.client_ip, "172.68.21.4")
        self.assertEqual(entry.method, "POST")
        self.assertEqual(entry.path, "/api/v1/checkout")
        self.assertEqual(entry.status_code, 200)
        self.assertEqual(entry.level, "success")
        self.assertEqual(entry.size, "4.7KB")
        self.assertEqual(entry.duration, "18.4ms")
        self.assertEqual(entry.line_number, 1)

    def test_parse_nginx_error_log(self) -> None:
        raw = '2026/10/29 15:42:03 [error] 14205#14205: *8491 connect() failed (111: Connection refused)'
        entry = parse_log_line(raw, "Nginx Error", 42)
        self.assertEqual(entry.timestamp, "2026/10/29 15:42:03")
        self.assertEqual(entry.level, "error")
        self.assertEqual(entry.pid, "14205#14205")
        self.assertIn("connect() failed", entry.text)

    def test_parse_syslog_line(self) -> None:
        raw = "Oct 29 15:40:12 72-server sshd[14012]: Accepted publickey for root from 10.0.0.1"
        entry = parse_log_line(raw, "Syslog", 100)
        self.assertEqual(entry.timestamp, "Oct 29 15:40:12")
        self.assertEqual(entry.unit, "sshd")
        self.assertEqual(entry.pid, "14012")
        self.assertIn("Accepted publickey", entry.text)

    def test_ring_buffer_bounded(self) -> None:
        session = LogStreamSession(
            config=LogStreamConfig(name="Test Stream"),
            status=LogStreamStatus.STREAMING,
        )
        # Append 12,000 entries
        for i in range(12000):
            session.ring_buffer.append(
                LogEntry(
                    timestamp="now",
                    level="info",
                    source="test",
                    text=f"Line {i}",
                    raw=f"Line {i}",
                    line_number=i,
                )
            )

        # Maxlen is 10,000
        self.assertEqual(len(session.ring_buffer), 10000)
        # Oldest line should be Line 2000
        self.assertEqual(session.ring_buffer[0].text, "Line 2000")
        # Latest line should be Line 11999
        self.assertEqual(session.ring_buffer[-1].text, "Line 11999")


class TestLogStreamManagerAsync(unittest.IsolatedAsyncioTestCase):
    async def test_manager_lifecycle(self) -> None:
        manager = LogStreamManager()

        hang_event = asyncio.Event()

        async def mock_readline() -> str:
            if not hasattr(mock_readline, "count"):
                mock_readline.count = 0
            mock_readline.count += 1
            if mock_readline.count == 1:
                return '10.0.0.1 - - [29/Oct/2026:15:42:01 +0000] "GET /healthz HTTP/1.1" 200 18 0.4ms\n'
            elif mock_readline.count == 2:
                return '2026/10/29 15:42:03 [error] 14205#14205: database timeout\n'
            else:
                await hang_event.wait()
                return ""

        mock_stdout = MagicMock()
        mock_stdout.readline = mock_readline
        mock_stdout.at_eof = MagicMock(return_value=False)

        mock_process = MagicMock()
        mock_process.stdout = mock_stdout
        mock_process.terminate = MagicMock()
        mock_process.wait = AsyncMock(return_value=0)

        mock_conn = MagicMock()
        mock_conn.create_process = AsyncMock(return_value=mock_process)

        received_entries: list[LogEntry] = []

        config = LogStreamConfig(
            id="test-stream-1",
            name="Mock Access",
            source_type=LogSourceType.FILE,
            target_path="/var/log/test.log",
        )

        res = await manager.start_stream(config, mock_conn, lambda entry: received_entries.append(entry))
        self.assertTrue(res.ok)
        self.assertEqual(manager.get_session("test-stream-1").status, LogStreamStatus.STREAMING)

        # Allow async reader task to process lines
        await asyncio.sleep(0.05)

        self.assertEqual(len(received_entries), 2)
        self.assertEqual(received_entries[0].status_code, 200)
        self.assertEqual(received_entries[1].level, "error")

        # Test pause/resume
        manager.pause_stream("test-stream-1")
        self.assertEqual(manager.get_session("test-stream-1").status, LogStreamStatus.PAUSED)
        manager.resume_stream("test-stream-1")
        self.assertEqual(manager.get_session("test-stream-1").status, LogStreamStatus.STREAMING)

        # Test clear
        manager.clear_stream_buffer("test-stream-1")
        self.assertEqual(len(manager.get_session("test-stream-1").ring_buffer), 0)

        # Test stop
        hang_event.set()
        stop_res = await manager.stop_stream("test-stream-1")
        self.assertTrue(stop_res.ok)
        self.assertEqual(manager.get_session("test-stream-1").status, LogStreamStatus.STOPPED)
        mock_process.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
