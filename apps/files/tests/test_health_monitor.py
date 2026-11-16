from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from core.health_monitor import (
    ServerHealthCollector,
    format_bytes,
    format_uptime,
    kill_remote_process,
    scan_remote_directory_sizes,
)
from core.result import OperationResult


MOCK_BATCH_OUTPUT_1 = """\
cpu  1000 200 500 8000 100 50 20 0 0 0
cpu0 500 100 250 4000 50 25 10 0 0 0
cpu1 500 100 250 4000 50 25 10 0 0 0
===MEM===
MemTotal:        8192000 kB
MemFree:         1024000 kB
MemAvailable:    5120000 kB
Buffers:          200000 kB
Cached:          3896000 kB
SwapTotal:       2097152 kB
SwapFree:        1887436 kB
===LOAD===
0.42 0.38 0.31 1/450 14210
===NET===
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 1000000    1000    0    0    0     0          0         0  1000000    1000    0    0    0     0       0          0
  eth0: 50000000   50000    0    0    0     0          0         0 20000000   25000    0    0    0     0       0          0
===UPTIME===
123456.78 987654.32
===OS===
PRETTY_NAME="Ubuntu 24.04 LTS"
Linux 6.8.0-45-generic #45-Ubuntu SMP
===DF===
Filesystem     1024-blocks      Used Available Capacity Mounted on
/dev/nvme0n1p2   102400000  35840000  66560000      35% /
/dev/nvme0n1p3    51200000  18944000  32256000      37% /var
/dev/sda1        256000000  12800000 243200000       5% /home
tmpfs              4096000         0   4096000       0% /dev/shm
===PS===
  PID USER     %CPU %MEM STAT COMMAND
14201 www-data 12.4  1.2 S    nginx: worker process
  984 root      4.8  4.1 S    dockerd -H fd://
 2109 postgres  1.8  3.6 S    postgres: writer process
"""

MOCK_BATCH_OUTPUT_2 = """\
cpu  1200 210 550 8200 110 55 25 0 0 0
cpu0 600 105 275 4100 55 28 12 0 0 0
cpu1 600 105 275 4100 55 27 13 0 0 0
===MEM===
MemTotal:        8192000 kB
MemFree:          924000 kB
MemAvailable:    5020000 kB
SwapTotal:       2097152 kB
SwapFree:        1887436 kB
===LOAD===
0.55 0.40 0.32 2/452 14350
===NET===
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
  eth0: 51000000   51000    0    0    0     0          0         0 20500000   25500    0    0    0     0       0          0
===UPTIME===
123458.78 987656.32
===OS===
PRETTY_NAME="Ubuntu 24.04 LTS"
===DF===
Filesystem     1024-blocks      Used Available Capacity Mounted on
/dev/nvme0n1p2   102400000  35840000  66560000      35% /
===PS===
  PID USER     %CPU %MEM STAT COMMAND
14201 www-data 15.1  1.2 R    nginx: worker process
"""


class TestServerHealthCollector(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.collector = ServerHealthCollector()

    def test_first_sample_parsing(self) -> None:
        snap = self.collector.parse_batch(MOCK_BATCH_OUTPUT_1, now=1000.0)

        self.assertEqual(snap.cpu_cores, 2)
        self.assertEqual(snap.load_avg, (0.42, 0.38, 0.31))
        self.assertEqual(snap.os_name, "Ubuntu 24.04 LTS")
        self.assertEqual(snap.net_interface, "eth0")
        self.assertEqual(snap.net_total_rx_bytes, 50000000)
        self.assertEqual(snap.net_total_tx_bytes, 20000000)

        # Memory: MemTotal 8192000 kB -> 8388608000 bytes
        # MemAvailable: 5120000 kB -> 5242880000 bytes
        # Used = 8388608000 - 5242880000 = 3145728000 bytes
        self.assertEqual(snap.mem_total_bytes, 8192000 * 1024)
        self.assertEqual(snap.mem_used_bytes, (8192000 - 5120000) * 1024)
        self.assertEqual(snap.mem_available_bytes, 5120000 * 1024)

        # Mounts: 3 non-pseudo filesystems (/ , /var, /home)
        self.assertEqual(len(snap.mounts), 3)
        mount_points = [m.mount_point for m in snap.mounts]
        self.assertIn("/", mount_points)
        self.assertIn("/var", mount_points)
        self.assertIn("/home", mount_points)

        # Root disk summary
        self.assertEqual(snap.disk_use_percent, 35.0)

        # Processes: 3 processes parsed
        self.assertEqual(len(snap.processes), 3)
        self.assertEqual(snap.processes[0].pid, 14201)
        self.assertEqual(snap.processes[0].user, "www-data")
        self.assertEqual(snap.processes[0].cpu_percent, 12.4)
        self.assertEqual(snap.processes[0].status, "Sleep")

    def test_consecutive_delta_sample_calculation(self) -> None:
        self.collector.parse_batch(MOCK_BATCH_OUTPUT_1, now=1000.0)
        # Sample 2 at now=1002.0 (elapsed = 2.0s)
        snap2 = self.collector.parse_batch(MOCK_BATCH_OUTPUT_2, now=1002.0)

        # Delta CPU calculations:
        # Total jiffies delta:
        # user: 1200 - 1000 = 200
        # nice: 210 - 200 = 10
        # system: 550 - 500 = 50
        # idle: 8200 - 8000 = 200
        # iowait: 110 - 100 = 10
        # irq: 55 - 50 = 5
        # softirq: 25 - 20 = 5
        # total_busy = 200+10+50+5+5 = 270
        # total_idle = 200+10 = 210
        # delta_total = 480
        # total_pct = 270 / 480 * 100 = 56.25% -> 56.2% or 56.3%
        self.assertGreater(snap2.cpu_percent, 50.0)
        self.assertLess(snap2.cpu_percent, 60.0)

        # Network delta:
        # rx_delta = 51000000 - 50000000 = 1000000 bytes over 2s = 500000 B/s
        # tx_delta = 20500000 - 20000000 = 500000 bytes over 2s = 250000 B/s
        self.assertEqual(snap2.net_rx_rate_bytes_per_sec, 500000.0)
        self.assertEqual(snap2.net_tx_rate_bytes_per_sec, 250000.0)

    def test_format_helpers(self) -> None:
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1024 * 500), "500 KB")
        self.assertEqual(format_bytes(1024 * 1024 * 2400), "2.3 GB")
        self.assertEqual(format_uptime(3665), "1h 1m")
        self.assertEqual(format_uptime(90065), "1d 1h 1m")

    async def test_kill_process_and_directory_scan(self) -> None:
        mock_conn = MagicMock()
        mock_conn.run_command = AsyncMock(
            return_value=OperationResult.success("Signal sent", data={"stdout": "", "exit_status": 0})
        )

        res = await kill_remote_process(mock_conn, 14201, force=False)
        self.assertTrue(res.ok)
        mock_conn.run_command.assert_called_with("kill -15 14201")

        # Test directory scan
        mock_conn.run_command = AsyncMock(
            return_value=OperationResult.success(
                "Scan complete",
                data={"stdout": "14.2G\t/var/lib/docker\n4.8G\t/var/log\n", "exit_status": 0},
            )
        )
        dirs = await scan_remote_directory_sizes(mock_conn)
        self.assertEqual(len(dirs), 2)
        self.assertEqual(dirs[0].path, "/var/lib/docker")
        self.assertEqual(dirs[0].size_formatted, "14.2G")
        self.assertIn("container", dirs[0].description.lower())


if __name__ == "__main__":
    unittest.main()
