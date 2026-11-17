from __future__ import annotations

import unittest
from core.services_manager import (
    SystemdServicesCollector,
    categorize_service,
    detect_service_ports,
)

MOCK_LIST_UNITS_OUTPUT = """
  UNIT                         LOAD   ACTIVE SUB     DESCRIPTION
  cron.service                 loaded active running Regular background program processing daemon
● celery-worker.service        loaded failed failed  Celery Distributed Task Worker
  docker.service               loaded active running Docker Application Container Engine
  nginx.service                loaded active running A high performance web server and a reverse proxy server
  postgresql.service           loaded active running PostgreSQL RDBMS Database Server
  redis-server.service         loaded active running Advanced key-value store
  apache2.service              loaded inactive dead   The Apache HTTP Server
  ssh.service                  loaded active running OpenBSD Secure Shell server
===BOOT===
UNIT FILE                    STATE           VENDOR PRESET
apache2.service              disabled        enabled      
celery-worker.service        enabled         enabled      
cron.service                 enabled         enabled      
docker.service               enabled         enabled      
nginx.service                enabled         enabled      
postgresql.service           enabled         enabled      
redis-server.service         enabled         enabled      
ssh.service                  enabled         enabled      
"""

MOCK_PROPERTIES_OUTPUT = """
Id=nginx.service
Description=A high performance web server and a reverse proxy server
LoadState=loaded
ActiveState=active
SubState=running
UnitFileState=enabled
MainPID=14201
MemoryCurrent=98784256
CPUUsageNSec=1420847000
TasksCurrent=4
TasksMax=4096
Restart=always
ExecStart={ path=/usr/sbin/nginx ; argv[]=/usr/sbin/nginx -g daemon on; master_process on; }
"""

MOCK_JOURNAL_OUTPUT = """
-- Journal begins at Tue 2026-10-13 04:12:08 UTC, ends at Tue 2026-10-27 09:50:22 UTC. --
Oct 27 09:40:12 srv1 systemd[1]: Starting nginx.service - A high performance web server...
Oct 27 09:40:12 srv1 nginx[14201]: nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
Oct 27 09:40:12 srv1 nginx[14201]: nginx: configuration file /etc/nginx/nginx.conf test is successful
Oct 27 09:40:12 srv1 systemd[1]: Started nginx.service - A high performance web server and a reverse proxy server.
Oct 27 09:42:01 srv1 nginx[14205]: 172.68.21.4 - - [27/Oct/2026:09:42:01 +0000] "GET /api/v1/health HTTP/1.1" 200 42 "-" "HealthCheck/1.0"
Oct 27 09:43:10 srv1 nginx[14205]: 172.68.21.4 - - [27/Oct/2026:09:43:10 +0000] "GET /missing HTTP/1.1" 404 184 "-" "Browser"
Oct 27 09:45:12 srv1 celery[1882288]: CRITICAL/MainProcess Unhandled Exception: kombu.exceptions.OperationalError: Connection refused
"""


class TestServicesManager(unittest.IsolatedAsyncioTestCase):
    def test_parse_inventory(self) -> None:
        snap = SystemdServicesCollector.parse_inventory(MOCK_LIST_UNITS_OUTPUT, now=1000.0)
        self.assertEqual(snap.total_count, 8)
        self.assertEqual(snap.running_count, 6)
        self.assertEqual(snap.failed_count, 1)
        self.assertEqual(snap.stopped_count, 1)
        self.assertEqual(snap.boot_enabled_count, 7)

        # Verify failed unit is sorted to the top
        self.assertEqual(snap.services[0].name, "celery-worker.service")
        self.assertTrue(snap.services[0].is_failed)
        self.assertTrue(snap.services[0].is_boot_enabled)
        self.assertEqual(snap.services[0].category, "worker")

        # Verify nginx unit
        nginx = next(s for s in snap.services if s.name == "nginx.service")
        self.assertTrue(nginx.is_running)
        self.assertFalse(nginx.is_failed)
        self.assertTrue(nginx.is_boot_enabled)
        self.assertEqual(nginx.category, "web")
        self.assertIn(":80", nginx.ports)

        # Verify stopped apache unit
        apache = next(s for s in snap.services if s.name == "apache2.service")
        self.assertFalse(apache.is_running)
        self.assertFalse(apache.is_boot_enabled)
        self.assertEqual(apache.active_state, "inactive")
        self.assertEqual(apache.sub_state, "dead")

    def test_parse_properties(self) -> None:
        props = SystemdServicesCollector.parse_properties(MOCK_PROPERTIES_OUTPUT)
        self.assertEqual(props.get("MainPID"), "14201")
        self.assertEqual(props.get("MemoryCurrent"), "98784256")
        self.assertEqual(props.get("Restart"), "always")
        self.assertEqual(props.get("TasksCurrent"), "4")

    def test_parse_journal(self) -> None:
        logs = SystemdServicesCollector.parse_journal(MOCK_JOURNAL_OUTPUT)
        self.assertEqual(len(logs), 7)
        self.assertEqual(logs[0].timestamp, "Oct 27 09:40:12")
        self.assertIn("systemd[1]", logs[0].sender)
        self.assertFalse(logs[0].is_error)

        # Verify error line detection
        error_entry = next(entry for entry in logs if "Unhandled Exception" in entry.message)
        self.assertTrue(error_entry.is_error)
        self.assertEqual(error_entry.priority, "err")

    def test_categorize_service(self) -> None:
        self.assertEqual(categorize_service("nginx.service"), "web")
        self.assertEqual(categorize_service("docker.service"), "container")
        self.assertEqual(categorize_service("postgresql.service"), "database")
        self.assertEqual(categorize_service("celery-worker.service"), "worker")
        self.assertEqual(categorize_service("fail2ban.service"), "security")
        self.assertEqual(categorize_service("systemd-journald.service"), "system")

    def test_detect_service_ports(self) -> None:
        self.assertIn(":80", detect_service_ports("nginx.service"))
        self.assertIn(":5432", detect_service_ports("postgresql.service"))
        self.assertIn(":6379", detect_service_ports("redis-server.service"))
        self.assertIn("docker.sock", detect_service_ports("docker.service"))
        self.assertEqual(detect_service_ports("custom-cron.service"), "")

    def test_validate_unit_name(self) -> None:
        from core.services_manager import validate_unit_name
        self.assertEqual(validate_unit_name("nginx.service"), "nginx.service")
        self.assertEqual(validate_unit_name("celery-worker@1.service"), "celery-worker@1.service")
        self.assertEqual(validate_unit_name("my_app.service"), "my_app.service")
        self.assertEqual(validate_unit_name("myapp"), "myapp.service")  # automatically appends .service

        # Path traversal and injection attempts must raise ValueError
        with self.assertRaises(ValueError):
            validate_unit_name("../evil.service")
        with self.assertRaises(ValueError):
            validate_unit_name("foo/bar.service")
        with self.assertRaises(ValueError):
            validate_unit_name("foo; rm -rf /")
        with self.assertRaises(ValueError):
            validate_unit_name("foo`id`")
        with self.assertRaises(ValueError):
            validate_unit_name("foo$(id)")
        with self.assertRaises(ValueError):
            validate_unit_name("")

    async def test_control_service_and_install(self) -> None:
        from core.services_manager import control_service, daemon_reload, install_unit_file
        from core.result import OperationResult

        class MockConnection:
            def __init__(self) -> None:
                self.commands: list[str] = []

            async def run_command(self, cmd: str) -> OperationResult:
                self.commands.append(cmd)
                return OperationResult.success("ok", data={"stdout": "ok"})

        mock = MockConnection()
        res = await control_service(mock, "nginx.service", "restart")
        self.assertTrue(res.ok)
        self.assertEqual(mock.commands[-1], "sudo -n systemctl restart nginx.service")

        res_reload = await daemon_reload(mock)
        self.assertTrue(res_reload.ok)
        self.assertEqual(mock.commands[-1], "sudo -n systemctl daemon-reload")

        res_install = await install_unit_file(mock, "test-api.service", "[Unit]\nDescription=Test", enable_and_start=True)
        self.assertTrue(res_install.ok)
        self.assertIn("base64 -d | sudo -n tee /etc/systemd/system/test-api.service", mock.commands[-1])
        self.assertIn("sudo -n systemctl enable --now test-api.service", mock.commands[-1])


if __name__ == "__main__":
    unittest.main()
