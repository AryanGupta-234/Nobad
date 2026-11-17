from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from core.remote_command import command_error, command_ok
from core.result import OperationResult


TELEMETRY_SHELL_COMMAND = (
    "cat /proc/stat; echo '===MEM==='; cat /proc/meminfo; echo '===LOAD==='; "
    "cat /proc/loadavg; echo '===NET==='; cat /proc/net/dev; echo '===UPTIME==='; "
    "cat /proc/uptime; echo '===OS==='; (cat /etc/os-release 2>/dev/null || uname -srm); "
    "echo '===DF==='; df -P -k; echo '===PS==='; ps -eo pid,user:20,%cpu,%mem,stat,comm --sort=-%cpu | head -n 25"
)


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    user: str
    cpu_percent: float
    mem_percent: float
    mem_rss_bytes: int
    status: str
    command: str


@dataclass(frozen=True, slots=True)
class DiskMountInfo:
    filesystem: str
    mount_point: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    use_percent: float


@dataclass(frozen=True, slots=True)
class DirectorySizeInfo:
    path: str
    size_bytes: int
    size_formatted: str
    description: str


@dataclass(frozen=True, slots=True)
class ServerMetricsSnapshot:
    timestamp: float
    cpu_percent: float
    cpu_user_percent: float
    cpu_sys_percent: float
    cpu_iowait_percent: float
    cpu_cores: int
    load_avg: tuple[float, float, float]

    mem_total_bytes: int
    mem_used_bytes: int
    mem_available_bytes: int
    swap_total_bytes: int
    swap_used_bytes: int

    disk_total_bytes: int
    disk_used_bytes: int
    disk_free_bytes: int
    disk_use_percent: float

    net_interface: str
    net_rx_rate_bytes_per_sec: float
    net_tx_rate_bytes_per_sec: float
    net_total_rx_bytes: int
    net_total_tx_bytes: int

    uptime_seconds: float
    os_name: str
    kernel_version: str

    processes: tuple[ProcessInfo, ...]
    mounts: tuple[DiskMountInfo, ...]


def format_bytes(num_bytes: int | float) -> str:
    """Format bytes into human readable format (e.g. 2.4 GB, 120 KB)."""
    if num_bytes < 0:
        return "0 B"
    val = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024.0 or unit == "TB":
            if unit in ("B", "KB"):
                return f"{val:.0f} {unit}"
            return f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{val:.1f} TB"


def format_uptime(uptime_seconds: float) -> str:
    """Format uptime into human readable string like '14d 6h 32m'."""
    secs = int(max(0, uptime_seconds))
    days = secs // 86400
    secs %= 86400
    hours = secs // 3600
    secs %= 3600
    minutes = secs // 60
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or days > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


class ServerHealthCollector:
    """
    Parses compound telemetry batch output from Linux server `/proc`, `df`, and `ps`
    and maintains historical jiffies/bytes state to compute accurate delta rates.
    """

    def __init__(self) -> None:
        self._prev_time: float | None = None
        self._prev_cpu_total: int | None = None
        self._prev_cpu_idle: int | None = None
        self._prev_cpu_user: int | None = None
        self._prev_cpu_sys: int | None = None
        self._prev_cpu_iowait: int | None = None
        self._prev_net_rx: int | None = None
        self._prev_net_tx: int | None = None
        self._last_snapshot: ServerMetricsSnapshot | None = None

    @property
    def last_snapshot(self) -> ServerMetricsSnapshot | None:
        return self._last_snapshot

    def reset(self) -> None:
        self._prev_time = None
        self._prev_cpu_total = None
        self._prev_cpu_idle = None
        self._prev_cpu_user = None
        self._prev_cpu_sys = None
        self._prev_cpu_iowait = None
        self._prev_net_rx = None
        self._prev_net_tx = None
        self._last_snapshot = None

    def parse_batch(self, raw_output: str, now: float | None = None) -> ServerMetricsSnapshot:
        if now is None:
            now = time.time()

        elapsed = 2.0
        if self._prev_time is not None and now > self._prev_time:
            elapsed = max(0.1, now - self._prev_time)
        self._prev_time = now

        sections = self._split_sections(raw_output)

        # 1. Parse CPU from /proc/stat
        cpu_metrics, core_count = self._parse_proc_stat(sections.get("STAT", ""))

        # 2. Parse Memory from /proc/meminfo
        mem_metrics = self._parse_proc_meminfo(sections.get("MEM", ""))

        # 3. Parse Load Average from /proc/loadavg
        load_avg = self._parse_proc_loadavg(sections.get("LOAD", ""))

        # 4. Parse Network from /proc/net/dev
        net_metrics = self._parse_proc_net_dev(sections.get("NET", ""), elapsed)

        # 5. Parse Uptime from /proc/uptime
        uptime_seconds = self._parse_proc_uptime(sections.get("UPTIME", ""))

        # 6. Parse OS Info from os-release or uname
        os_name, kernel_ver = self._parse_os_info(sections.get("OS", ""))

        # 7. Parse Mounts from df -P -k
        mounts, disk_totals = self._parse_df(sections.get("DF", ""))

        # 8. Parse Processes from ps
        processes = self._parse_ps(sections.get("PS", ""), mem_metrics["total_bytes"])

        snapshot = ServerMetricsSnapshot(
            timestamp=now,
            cpu_percent=cpu_metrics["total_pct"],
            cpu_user_percent=cpu_metrics["user_pct"],
            cpu_sys_percent=cpu_metrics["sys_pct"],
            cpu_iowait_percent=cpu_metrics["iowait_pct"],
            cpu_cores=core_count,
            load_avg=load_avg,
            mem_total_bytes=mem_metrics["total_bytes"],
            mem_used_bytes=mem_metrics["used_bytes"],
            mem_available_bytes=mem_metrics["avail_bytes"],
            swap_total_bytes=mem_metrics["swap_total_bytes"],
            swap_used_bytes=mem_metrics["swap_used_bytes"],
            disk_total_bytes=disk_totals["total"],
            disk_used_bytes=disk_totals["used"],
            disk_free_bytes=disk_totals["free"],
            disk_use_percent=disk_totals["use_percent"],
            net_interface=net_metrics["iface"],
            net_rx_rate_bytes_per_sec=net_metrics["rx_rate"],
            net_tx_rate_bytes_per_sec=net_metrics["tx_rate"],
            net_total_rx_bytes=net_metrics["total_rx"],
            net_total_tx_bytes=net_metrics["total_tx"],
            uptime_seconds=uptime_seconds,
            os_name=os_name,
            kernel_version=kernel_ver,
            processes=processes,
            mounts=mounts,
        )
        self._last_snapshot = snapshot
        return snapshot

    def _split_sections(self, text: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        marker_pattern = re.compile(r"^===([A-Z0-9_]+)===$", re.MULTILINE)
        splits = list(marker_pattern.finditer(text))

        if not splits:
            sections["STAT"] = text
            return sections

        # First segment before any marker is STAT
        sections["STAT"] = text[: splits[0].start()].strip()

        for idx, match in enumerate(splits):
            tag = match.group(1)
            start_pos = match.end()
            end_pos = splits[idx + 1].start() if idx + 1 < len(splits) else len(text)
            sections[tag] = text[start_pos:end_pos].strip()

        return sections

    def _parse_proc_stat(self, text: str) -> tuple[dict[str, float], int]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        core_count = 0
        total_line = ""

        for line in lines:
            if line.startswith("cpu "):
                total_line = line
            elif line.startswith("cpu") and line[3:4].isdigit():
                core_count += 1

        if core_count == 0:
            core_count = 1

        metrics = {
            "total_pct": 0.0,
            "user_pct": 0.0,
            "sys_pct": 0.0,
            "iowait_pct": 0.0,
        }

        if not total_line:
            return metrics, core_count

        parts = total_line.split()
        if len(parts) < 5:
            return metrics, core_count

        try:
            # cpu user nice system idle iowait irq softirq steal guest
            user = int(parts[1])
            nice = int(parts[2])
            system = int(parts[3])
            idle = int(parts[4])
            iowait = int(parts[5]) if len(parts) > 5 else 0
            irq = int(parts[6]) if len(parts) > 6 else 0
            softirq = int(parts[7]) if len(parts) > 7 else 0
            steal = int(parts[8]) if len(parts) > 8 else 0

            idle_all = idle + iowait
            system_all = system + irq + softirq
            user_all = user + nice
            total = idle_all + system_all + user_all + steal

            if self._prev_cpu_total is not None and total > self._prev_cpu_total:
                delta_total = max(1, total - self._prev_cpu_total)
                delta_idle = max(0, idle_all - (self._prev_cpu_idle or 0))
                delta_user = max(0, user_all - (self._prev_cpu_user or 0))
                delta_sys = max(0, system_all - (self._prev_cpu_sys or 0))
                delta_iowait = max(0, iowait - (self._prev_cpu_iowait or 0))

                total_busy = max(0, delta_total - delta_idle)
                metrics["total_pct"] = min(100.0, round((total_busy / delta_total) * 100.0, 1))
                metrics["user_pct"] = min(100.0, round((delta_user / delta_total) * 100.0, 1))
                metrics["sys_pct"] = min(100.0, round((delta_sys / delta_total) * 100.0, 1))
                metrics["iowait_pct"] = min(100.0, round((delta_iowait / delta_total) * 100.0, 1))
            else:
                # First sample fallback: estimate from overall counter ratio
                if total > 0:
                    metrics["total_pct"] = min(100.0, round(((total - idle_all) / total) * 100.0, 1))
                    metrics["user_pct"] = min(100.0, round((user_all / total) * 100.0, 1))
                    metrics["sys_pct"] = min(100.0, round((system_all / total) * 100.0, 1))
                    metrics["iowait_pct"] = min(100.0, round((iowait / total) * 100.0, 1))

            self._prev_cpu_total = total
            self._prev_cpu_idle = idle_all
            self._prev_cpu_user = user_all
            self._prev_cpu_sys = system_all
            self._prev_cpu_iowait = iowait

        except (ValueError, IndexError):
            pass

        return metrics, core_count

    def _parse_proc_meminfo(self, text: str) -> dict[str, int]:
        info: dict[str, int] = {}
        for line in text.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                tokens = v.strip().split()
                if tokens:
                    try:
                        # Values in /proc/meminfo are in kB
                        info[k.strip()] = int(tokens[0]) * 1024
                    except ValueError:
                        continue

        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", info.get("MemFree", 0))
        used = max(0, total - available)

        swap_total = info.get("SwapTotal", 0)
        swap_free = info.get("SwapFree", 0)
        swap_used = max(0, swap_total - swap_free)

        return {
            "total_bytes": total,
            "used_bytes": used,
            "avail_bytes": available,
            "swap_total_bytes": swap_total,
            "swap_used_bytes": swap_used,
        }

    def _parse_proc_loadavg(self, text: str) -> tuple[float, float, float]:
        parts = text.strip().split()
        if len(parts) >= 3:
            try:
                return (float(parts[0]), float(parts[1]), float(parts[2]))
            except ValueError:
                pass
        return (0.0, 0.0, 0.0)

    def _parse_proc_net_dev(self, text: str, elapsed: float) -> dict[str, Any]:
        best_iface = "eth0"
        max_bytes = -1
        total_rx = 0
        total_tx = 0

        # Typical format:
        # face |bytes    packets errs drop fifo frame compressed multicast|bytes ...
        # eth0: 104928 293 0 0 ...
        for line in text.splitlines():
            if ":" not in line:
                continue
            iface, stats = line.split(":", 1)
            iface = iface.strip()
            if iface in ("lo", "docker0") or iface.startswith(("veth", "br-")):
                continue

            nums = [int(tok) for tok in stats.split() if tok.isdigit()]
            if len(nums) >= 9:
                rx_bytes = nums[0]
                tx_bytes = nums[8]
                if rx_bytes + tx_bytes > max_bytes:
                    max_bytes = rx_bytes + tx_bytes
                    best_iface = iface
                    total_rx = rx_bytes
                    total_tx = tx_bytes

        rx_rate = 0.0
        tx_rate = 0.0
        if self._prev_net_rx is not None and total_rx >= self._prev_net_rx and elapsed > 0:
            rx_rate = max(0.0, (total_rx - self._prev_net_rx) / elapsed)
            tx_rate = max(0.0, (total_tx - (self._prev_net_tx or 0)) / elapsed)

        self._prev_net_rx = total_rx
        self._prev_net_tx = total_tx

        return {
            "iface": best_iface,
            "rx_rate": round(rx_rate, 1),
            "tx_rate": round(tx_rate, 1),
            "total_rx": total_rx,
            "total_tx": total_tx,
        }

    def _parse_proc_uptime(self, text: str) -> float:
        parts = text.strip().split()
        if parts:
            try:
                return float(parts[0])
            except ValueError:
                pass
        return 0.0

    def _parse_os_info(self, text: str) -> tuple[str, str]:
        os_name = "Linux"
        kernel_ver = ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("PRETTY_NAME="):
                os_name = line.split("=", 1)[1].strip('"\'')
            elif "Linux" in line and not kernel_ver:
                kernel_ver = line
        return os_name, kernel_ver

    def _parse_df(self, text: str) -> tuple[tuple[DiskMountInfo, ...], dict[str, Any]]:
        mounts: list[DiskMountInfo] = []
        root_total = 0
        root_used = 0
        root_free = 0
        root_pct = 0.0

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("Filesystem"):
                continue
            parts = line.split()
            if len(parts) >= 6:
                fs = parts[0]
                # Filter pseudo filesystems
                if fs in ("tmpfs", "devtmpfs", "udev", "overlay", "shm", "none") or "/snap/" in line:
                    continue
                try:
                    total_b = int(parts[1]) * 1024
                    used_b = int(parts[2]) * 1024
                    free_b = int(parts[3]) * 1024
                    pct_str = parts[4].rstrip("%")
                    pct = float(pct_str) if pct_str.replace(".", "", 1).isdigit() else 0.0
                    mount_pt = parts[5]

                    mount_info = DiskMountInfo(
                        filesystem=fs,
                        mount_point=mount_pt,
                        total_bytes=total_b,
                        used_bytes=used_b,
                        free_bytes=free_b,
                        use_percent=pct,
                    )
                    mounts.append(mount_info)

                    if mount_pt == "/":
                        root_total = total_b
                        root_used = used_b
                        root_free = free_b
                        root_pct = pct
                except (ValueError, IndexError):
                    continue

        # If no explicit / mount found, use the first entry
        if root_total == 0 and mounts:
            root_total = mounts[0].total_bytes
            root_used = mounts[0].used_bytes
            root_free = mounts[0].free_bytes
            root_pct = mounts[0].use_percent

        return tuple(mounts), {
            "total": root_total,
            "used": root_used,
            "free": root_free,
            "use_percent": root_pct,
        }

    def _parse_ps(self, text: str, total_mem_bytes: int) -> tuple[ProcessInfo, ...]:
        processes: list[ProcessInfo] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("PID"):
                continue
            parts = line.split(None, 5)
            if len(parts) >= 6:
                try:
                    pid = int(parts[0])
                    user = parts[1]
                    cpu_pct = float(parts[2])
                    mem_pct = float(parts[3])
                    status = parts[4]
                    cmd = parts[5]

                    # Translate status code to friendly string
                    stat_name = "Running" if "R" in status else "Sleep"
                    if "Z" in status:
                        stat_name = "Zombie"
                    elif "T" in status or "t" in status:
                        stat_name = "Stopped"

                    rss_bytes = int(total_mem_bytes * (mem_pct / 100.0))

                    processes.append(
                        ProcessInfo(
                            pid=pid,
                            user=user,
                            cpu_percent=cpu_pct,
                            mem_percent=mem_pct,
                            mem_rss_bytes=rss_bytes,
                            status=stat_name,
                            command=cmd,
                        )
                    )
                except (ValueError, IndexError):
                    continue

        return tuple(processes)


async def kill_remote_process(connection: Any, pid: int, force: bool = False) -> OperationResult:
    """Send SIGTERM (15) or SIGKILL (9) to a remote process over SSH."""
    if connection is None:
        return OperationResult.failure("Cannot kill process: No active SSH connection.")
    sig = "-9" if force else "-15"
    cmd = f"kill {sig} {int(pid)}"
    try:
        res = await connection.run_command(cmd)
        if command_ok(res):
            return OperationResult.success(f"Signal {sig} delivered to PID {pid}.")
        return OperationResult.failure(command_error(res, f"Couldn't stop process {pid}"))
    except Exception as exc:
        return OperationResult.failure(f"Error terminating PID {pid}: {exc}")


async def scan_remote_directory_sizes(connection: Any, base_paths: tuple[str, ...] = ("/var", "/home")) -> tuple[DirectorySizeInfo, ...]:
    """Scan large directory consumers using du over SSH."""
    if connection is None:
        return ()
    paths_str = " ".join(base_paths)
    cmd = f"du -ah -d 1 {paths_str} 2>/dev/null | sort -hr | head -n 15"
    try:
        res = await connection.run_command(cmd)
        if not res.ok or not res.data:
            return ()
        stdout = res.data.get("stdout", "")
        results: list[DirectorySizeInfo] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                size_str, path = parts[0], parts[1]
                # Simple description heuristic
                desc = "Directory"
                if "docker" in path:
                    desc = "Container images & overlays"
                elif "log" in path:
                    desc = "System and application logs"
                elif "cache" in path:
                    desc = "Package and runtime caches"
                elif "www" in path or "html" in path:
                    desc = "Web server document root"
                elif "/home" in path:
                    desc = "User workspace and data"

                results.append(
                    DirectorySizeInfo(
                        path=path,
                        size_bytes=0,
                        size_formatted=size_str,
                        description=desc,
                    )
                )
        return tuple(results)
    except Exception:
        return ()
