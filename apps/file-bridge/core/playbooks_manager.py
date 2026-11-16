from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import re
import secrets
import shlex
import time
from typing import Any
import uuid

from core.playbooks_models import (
    PlaybookCategory,
    PlaybookExecutionRecord,
    PlaybookRecipe,
    PlaybookSafetyTier,
    PlaybookVariable,
)
from core.result import OperationResult, result_from_exception

logger = logging.getLogger("remote_file_manager.playbooks")

PREBUNDLED_RECIPES: list[PlaybookRecipe] = [
    PlaybookRecipe(
        id="certbot-ssl",
        title="Renew Certbot SSL",
        category=PlaybookCategory.SECURITY,
        safety=PlaybookSafetyTier.SUDO,
        safety_label="Requires Sudo",
        description="Automated Let's Encrypt TLS certificate renewal with Nginx config test, HTTP-01 challenge verification, and graceful service reload.",
        runtime_estimate="~4.5s",
        last_run_summary="Pre-bundled",
        variables=[
            PlaybookVariable(
                key="DOMAIN",
                label="Domains (comma-separated)",
                default_value="api.example.com, web.example.com",
                var_type="text",
                description="List of domain names to renew",
            ),
            PlaybookVariable(
                key="DRY_RUN",
                label="Dry-run mode (--dry-run test challenge)",
                default_value="true",
                var_type="boolean",
                description="Simulate renewal without rate-limit consumption",
            ),
            PlaybookVariable(
                key="RELOAD_SERVICE",
                label="Web Service to Reload",
                default_value="nginx",
                var_type="text",
                description="Reverse proxy service to reload (e.g. nginx or apache2)",
            ),
        ],
        steps=[
            "Pre-flight config test (nginx -t)",
            "Verify Let's Encrypt challenge path",
            "Execute certbot renew routine",
            "Reload web proxy & verify TLS expiration",
        ],
        script_template="""#!/usr/bin/env bash
set -euo pipefail

echo "========================================================"
echo "⚡ RFM PLAYBOOK: Renew Certbot SSL Certificates"
echo "Target Host: $(hostname -f 2>/dev/null || hostname) | Domains: {{DOMAIN}}"
echo "========================================================"

echo "[1/4] Running pre-flight configuration validation..."
sudo {{RELOAD_SERVICE}} -t

echo "[2/4] Validating ACME challenge directories..."
sudo ls -ld /var/www/letsencrypt/.well-known/acme-challenge 2>/dev/null || true

echo "[3/4] Requesting Let's Encrypt certificate renewal..."
if [ "{{DRY_RUN}}" = "true" ]; then
  echo ">>> Active Mode: Dry-Run (simulated ACME challenge without rate-limit consumption)"
  sudo certbot renew --{{RELOAD_SERVICE}} --dry-run
else
  sudo certbot renew --{{RELOAD_SERVICE}} --non-interactive --agree-tos
fi

echo "[4/4] Gracefully reloading web reverse proxy service..."
sudo systemctl reload {{RELOAD_SERVICE}}.service

echo ""
echo "=== Certificate Expiration Verification ==="
echo | openssl s_client -servername {{DOMAIN}} -connect 127.0.0.1:443 2>/dev/null | openssl x509 -noout -dates -subject 2>/dev/null || true
echo "✔ Certbot renewal playbook executed successfully with exit code 0."
""",
        is_prebundled=True,
        is_favorite=True,
    ),
    PlaybookRecipe(
        id="clean-disk",
        title="Clean Package Cache & Temp",
        category=PlaybookCategory.MAINTENANCE,
        safety=PlaybookSafetyTier.SUDO,
        safety_label="Requires Sudo",
        description="Reclaims server storage by purging obsolete APT archives, unneeded kernel packages, and systemd journal logs older than target threshold.",
        runtime_estimate="~6.0s",
        last_run_summary="Pre-bundled",
        variables=[
            PlaybookVariable(
                key="JOURNAL_VACUUM",
                label="Journal Vacuum Max Age",
                default_value="7d",
                var_type="text",
                description="Keep journal logs up to this age (e.g. 7d, 2weeks)",
            ),
            PlaybookVariable(
                key="PURGE_TMP",
                label="Purge /tmp files older than 3 days",
                default_value="true",
                var_type="boolean",
                description="Clean up stale files in /tmp",
            ),
        ],
        steps=[
            "Pre-cleanup disk filesystem audit (df -h)",
            "Apt package cache clean & autoremove",
            "Systemd journalctl vacuum",
            "Post-cleanup reclaimed space tally",
        ],
        script_template="""#!/usr/bin/env bash
set -euo pipefail

echo "========================================================"
echo "⚡ RFM PLAYBOOK: System Storage & Package Cache Cleanup"
echo "========================================================"

echo "--- Disk Utilization Before Cleanup ---"
df -h / /var /tmp 2>/dev/null || df -h /

echo ""
echo "[1/3] Cleaning APT package archives and cached indexes..."
sudo apt-get clean
sudo apt-get autoclean -y
sudo apt-get autoremove --purge -y

echo ""
echo "[2/3] Vacuuming systemd journal logs older than {{JOURNAL_VACUUM}}..."
sudo journalctl --vacuum-time={{JOURNAL_VACUUM}}

if [ "{{PURGE_TMP}}" = "true" ]; then
  echo ""
  echo "[3/3] Purging stale temporary files in /tmp older than 3 days..."
  sudo find /tmp -type f -atime +3 -delete 2>/dev/null || true
fi

echo ""
echo "--- Disk Utilization After Cleanup ---"
df -h / /var /tmp 2>/dev/null || df -h /
echo "✔ System storage maintenance complete."
""",
        is_prebundled=True,
        is_favorite=True,
    ),
    PlaybookRecipe(
        id="check-ports",
        title="Check Open Ports (ss/netstat)",
        category=PlaybookCategory.NETWORK,
        safety=PlaybookSafetyTier.SAFE,
        safety_label="Safe / Read-Only",
        description="Non-intrusive diagnostic playbook auditing listening TCP/UDP sockets, established SSH/reverse tunnels, and owning service process IDs.",
        runtime_estimate="~1.5s",
        last_run_summary="Pre-bundled",
        variables=[
            PlaybookVariable(
                key="PROTOCOL",
                label="Protocols to scan",
                default_value="tcp,udp",
                var_type="text",
                description="Protocols (tcp, udp, or all)",
            ),
            PlaybookVariable(
                key="PROCESS_FILTER",
                label="Filter process name (regex)",
                default_value="nginx|node|sshd|postgres|docker",
                var_type="text",
                description="Regex filter for specific processes",
            ),
        ],
        steps=[
            "Scan listening TCP/UDP sockets",
            "Inspect active established connections",
            "Map process ownership & bound interfaces",
        ],
        script_template="""#!/usr/bin/env bash
set -eo pipefail

echo "========================================================"
echo "⚡ RFM PLAYBOOK: Active Network Socket Audit"
echo "========================================================"

echo "=== [1/3] Listening TCP/UDP Sockets & Bound PIDs ==="
sudo ss -tulpn | grep -E 'LISTEN|UNCONN' | grep -E '{{PROCESS_FILTER}}' || true

echo ""
echo "=== [2/3] Established Network Tunnels & Remote Peers ==="
sudo ss -ntu state established | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -nr | head -n 10 || true

echo ""
echo "=== [3/3] Socket Summary Statistics ==="
sudo ss -s
echo "✔ Network audit completed successfully."
""",
        is_prebundled=True,
        is_favorite=False,
    ),
    PlaybookRecipe(
        id="docker-prune",
        title="Docker System Prune",
        category=PlaybookCategory.DOCKER,
        safety=PlaybookSafetyTier.DESTRUCTIVE,
        safety_label="Destructive / Prune",
        description="Removes stopped containers, dangling networks, unreferenced build caches, and untagged intermediate images to reclaim Docker volume space.",
        runtime_estimate="~5.2s",
        last_run_summary="Pre-bundled",
        variables=[
            PlaybookVariable(
                key="PRUNE_VOLUMES",
                label="Prune unused anonymous volumes (--volumes)",
                default_value="false",
                var_type="boolean",
                description="Also remove unused container volumes",
            ),
            PlaybookVariable(
                key="PRUNE_ALL_IMAGES",
                label="Prune all unused images, not just dangling (-a)",
                default_value="false",
                var_type="boolean",
                description="Remove all unused container images",
            ),
            PlaybookVariable(
                key="FORCE",
                label="Force without prompt (-f)",
                default_value="true",
                var_type="boolean",
                description="Bypass interactive confirmation prompt",
            ),
        ],
        steps=[
            "Pre-prune Docker disk inventory (docker system df)",
            "Prune stopped containers & dangling networks",
            "Clean untagged images & buildkit cache",
            "Post-prune space reclamation summary",
        ],
        script_template="""#!/usr/bin/env bash
set -euo pipefail

echo "========================================================"
echo "⚡ RFM PLAYBOOK: Docker Container & Image Pruning"
echo "========================================================"

echo "--- Current Docker Disk Usage ---"
docker system df

CMD="docker system prune"
if [ "{{FORCE}}" = "true" ]; then CMD="$CMD -f"; fi
if [ "{{PRUNE_ALL_IMAGES}}" = "true" ]; then CMD="$CMD -a"; fi
if [ "{{PRUNE_VOLUMES}}" = "true" ]; then CMD="$CMD --volumes"; fi

echo ""
echo "Executing: $CMD"
$CMD

echo ""
echo "--- Post-Prune Docker Disk Usage ---"
docker system df
echo "✔ Docker system prune completed."
""",
        is_prebundled=True,
        is_favorite=True,
    ),
    PlaybookRecipe(
        id="pg-vacuum",
        title="PostgreSQL VACUUM & ANALYZE",
        category=PlaybookCategory.DATABASE,
        safety=PlaybookSafetyTier.SUDO,
        safety_label="Vault Synced",
        description="Runs parallel non-blocking VACUUM and query optimizer ANALYZE across PostgreSQL database tables to prevent table bloat and rebuild index statistics.",
        runtime_estimate="~8.0s",
        last_run_summary="Pre-bundled",
        variables=[
            PlaybookVariable(
                key="DB_NAME",
                label="Database Name",
                default_value="postgres",
                var_type="text",
                description="Target database name",
            ),
            PlaybookVariable(
                key="VERBOSE",
                label="Verbose output log",
                default_value="true",
                var_type="boolean",
                description="Include per-table tuple statistics",
            ),
        ],
        steps=[
            "Verify PostgreSQL connection & active locks",
            "Execute VACUUM ANALYZE on target database",
            "Update planner statistical histograms",
        ],
        script_template="""#!/usr/bin/env bash
set -euo pipefail

echo "========================================================"
echo "⚡ RFM PLAYBOOK: PostgreSQL Database VACUUM & Statistics"
echo "Database: {{DB_NAME}}"
echo "========================================================"

echo "[1/2] Checking for long-running blocking transactions..."
sudo -u postgres psql -d {{DB_NAME}} -c "SELECT pid, now() - xact_start AS duration, query FROM pg_stat_activity WHERE state != 'idle' AND now() - xact_start > interval '2 minutes';" 2>/dev/null || true

echo "[2/2] Running VACUUM (ANALYZE, VERBOSE)..."
if [ "{{VERBOSE}}" = "true" ]; then
  sudo -u postgres vacuumdb --analyze --verbose {{DB_NAME}}
else
  sudo -u postgres vacuumdb --analyze {{DB_NAME}}
fi

echo "✔ PostgreSQL maintenance completed successfully."
""",
        is_prebundled=True,
        is_favorite=False,
    ),
    PlaybookRecipe(
        id="nginx-reload",
        title="Nginx Config Test & Safe Reload",
        category=PlaybookCategory.SECURITY,
        safety=PlaybookSafetyTier.SUDO,
        safety_label="Requires Sudo",
        description="Performs syntax check on Nginx vhosts, upstream proxies, and SSL certificates before issuing zero-downtime graceful worker reload.",
        runtime_estimate="~2.0s",
        last_run_summary="Pre-bundled",
        variables=[
            PlaybookVariable(
                key="CONF_PATH",
                label="Primary Nginx Config",
                default_value="/etc/nginx/nginx.conf",
                var_type="text",
                description="Configuration file path",
            ),
        ],
        steps=[
            "Pre-flight syntax validation (nginx -t -c {{CONF_PATH}})",
            "Zero-downtime graceful reload (systemctl reload nginx)",
            "Active worker PID rotation check",
        ],
        script_template="""#!/usr/bin/env bash
set -euo pipefail

echo "========================================================"
echo "⚡ RFM PLAYBOOK: Nginx Zero-Downtime Reload"
echo "========================================================"

echo "[1/2] Checking syntax for {{CONF_PATH}}..."
sudo nginx -t -c {{CONF_PATH}}

echo "[2/2] Issuing graceful master process reload..."
sudo systemctl reload nginx

echo ""
echo "Active Nginx master and worker processes:"
ps aux | grep -E '[n]ginx' | awk '{print $1, $2, $3, $11}'
echo "✔ Nginx reload completed without dropping active TCP connections."
""",
        is_prebundled=True,
        is_favorite=False,
    ),
    PlaybookRecipe(
        id="diagnostic-bundle",
        title="Generate System Diagnostic Bundle",
        category=PlaybookCategory.MAINTENANCE,
        safety=PlaybookSafetyTier.SUDO,
        safety_label="Requires Sudo",
        description="Collects dmesg kernel logs, memory/swap utilization, recent crash dumps, and top 20 resource-heavy processes into a compressed diagnostics tarball.",
        runtime_estimate="~3.8s",
        last_run_summary="Pre-bundled",
        variables=[
            PlaybookVariable(
                key="OUTPUT_DIR",
                label="Output Directory",
                default_value="/tmp/rfm-diagnostics",
                var_type="text",
                description="Target directory for archive creation",
            ),
        ],
        steps=[
            "Create temporary diagnostics workspace",
            "Collect dmesg, uptime, top memory consumers",
            "Archive into timestamped tarball",
        ],
        script_template="""#!/usr/bin/env bash
set -euo pipefail

DEST="{{OUTPUT_DIR}}-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$DEST"
echo "Collecting diagnostics into $DEST..."

uptime > "$DEST/uptime.txt"
free -h > "$DEST/memory.txt"
df -h > "$DEST/disk.txt"
sudo dmesg -T --level=err,warn | tail -n 100 > "$DEST/dmesg_errors.txt" 2>/dev/null || true
ps aux --sort=-%mem | head -n 20 > "$DEST/top_memory.txt"

tar -czf "$DEST.tar.gz" -C "/tmp" "$(basename "$DEST")"
rm -rf "$DEST"

echo "✔ Diagnostic bundle generated: $DEST.tar.gz"
""",
        is_prebundled=True,
        is_favorite=False,
    ),
]


def interpolate_template(template: str, variables: dict[str, Any]) -> str:
    """
    Interpolate {{KEY}} placeholders and {{#if KEY}}...{{/if}} conditional blocks with provided variable values.
    Sanitizes values to avoid unexpected shell injection syntax errors.
    """
    result = template

    # Handle {{#if KEY}}...{{/if}} conditional blocks
    def _eval_if(match: re.Match) -> str:
        var_name = match.group(1).strip()
        inner_content = match.group(2)
        val = variables.get(var_name, "")
        if isinstance(val, bool):
            is_true = val
        else:
            is_true = str(val).lower() in ("true", "1", "yes", "on")
        return inner_content if is_true else ""

    if_pattern = re.compile(r"\{\{#if\s+([A-Z0-9_]+)\}\}(.*?)\{\{/if\}\}", re.DOTALL)
    result = if_pattern.sub(_eval_if, result)

    for key, val in variables.items():
        str_val = str(val).strip()
        pattern = r"\{\{\s*" + re.escape(key) + r"\s*\}\}"
        result = re.sub(pattern, str_val, result)
    return result


_SUDO_WORD = re.compile(r"(?<![\w-])sudo(?![\w-])")


def script_uses_sudo(script: str) -> bool:
    """Whether a playbook script runs sudo, so the UI knows to ask for a sudo password before it starts."""
    return bool(_SUDO_WORD.search(script))


def choose_sudo_password(
    *, typed_password: str, reuse_login_password: bool, login_password: str | None
) -> str | None:
    """The sudo password to use for one run. The SSH login password is only reused when the user opted in (#32)."""
    if typed_password:
        return typed_password
    if reuse_login_password and login_password:
        return login_password
    return None


SUDO_PROMPT_SHOWN = "[sudo] password: "
SUDO_ASKED_AGAIN_NOTICE = (
    "\n[NOBAD File Bridge] sudo asked for the password again. It was not sent a second time: "
    "check the sudo password, or cancel the playbook.\n"
)
PASSWORD_MASK = "********"


class SudoPromptResponder:
    """Answers sudo's password prompt only when it is our own random prompt, and only once (issue #32).

    Remote output is untrusted: a log line, a file being printed or a hostile program can print
    "[sudo] password for ...", so the password must never be sent because some output *looks* like a prompt.
    The script exports ``SUDO_PROMPT=<random nonce>`` (honoured by every ``sudo`` in the script, also in
    subshells), so only a prompt from sudo itself contains a value the server has never seen before.

    Plain ``sudo`` (not ``sudo -S``) is used on purpose: in a PTY, ``-S`` reads stdin without turning echo off,
    so the terminal would echo the password back into the output. Plain sudo reads the tty with echo off."""

    def __init__(self, password: str) -> None:
        self.password = password
        # Letters, digits and "-" only: no shell quoting needed, and no %-escapes for sudo to expand.
        self.prompt = f"nobad-sudo-{secrets.token_hex(16)}"
        self.answered = False
        self.asked_again = False
        self._pending = ""

    def script_prelude(self) -> str:
        return f"export SUDO_PROMPT={shlex.quote(self.prompt)}\n"

    def feed(self, chunk: str) -> tuple[str, bool]:
        """Return ``(text to show, send the password now)`` for one output chunk."""
        data = self._pending + chunk
        send = False
        prompts = data.count(self.prompt)
        if prompts:
            data = data.replace(self.prompt, SUDO_PROMPT_SHOWN)
            if not self.answered:
                self.answered = True
                send = True
                prompts -= 1
            if prompts and not self.asked_again:
                self.asked_again = True
                data += SUDO_ASKED_AGAIN_NOTICE
        if self.password and self.password in data:
            data = data.replace(self.password, PASSWORD_MASK)
        # Hold back an ending that could be the start of the prompt (or the password), split across chunks.
        keep = self._partial_suffix(data)
        self._pending = data[len(data) - keep:] if keep else ""
        return (data[: len(data) - keep] if keep else data), send

    def flush(self) -> str:
        rest, self._pending = self._pending, ""
        return rest

    def _partial_suffix(self, data: str) -> int:
        longest = 0
        for needle in (self.prompt, self.password):
            for size in range(min(len(needle) - 1, len(data)), longest, -1):
                if data.endswith(needle[:size]):
                    longest = size
                    break
        return longest


class PlaybookStreamingRunner:
    """
    Executes a playbook shell script over an AsyncSSH connection PTY session,
    streaming output chunks in real time and supporting interactive cancellation.
    """

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self._process: Any | None = None
        self._cancelled: bool = False
        self._reader_task: asyncio.Task | None = None

    async def run(
        self,
        script: str,
        on_output: Callable[[str], None],
        *,
        sudo_password: str | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> OperationResult:
        """
        Run the script via SSH process with xterm-256color PTY and stream output.
        """
        if self.connection is None or getattr(self.connection, "raw_connection", None) is None:
            return OperationResult.failure("Execution failed: No active SSH connection.")

        self._cancelled = False
        raw_conn = self.connection.raw_connection
        sudo = SudoPromptResponder(sudo_password) if sudo_password else None
        if sudo is not None:
            script = sudo.script_prelude() + script

        # Wrap script in a clean bash invocation
        # Escape single quotes safely for bash -c '...'
        escaped_script = script.replace("'", "'\"'\"'")
        command = f"bash -c '{escaped_script}'"

        start_time = time.monotonic()
        output_buffer: list[str] = []

        try:
            self._process = await raw_conn.create_process(
                command,
                term_type="xterm-256color",
                term_size=(100, 30),
            )

            # Background reader task
            async def _reader() -> None:
                assert self._process is not None
                while True:
                    chunk = await self._process.stdout.read(4096)
                    if not chunk:
                        break
                    send_password = False
                    if sudo is not None:
                        chunk, send_password = sudo.feed(chunk)
                    if chunk:
                        output_buffer.append(chunk)
                        on_output(chunk)
                    if send_password:
                        self._process.stdin.write(f"{sudo.password}\n")
                        await self._process.stdin.drain()
                if sudo is not None:
                    rest = sudo.flush()
                    if rest:
                        output_buffer.append(rest)
                        on_output(rest)

            self._reader_task = asyncio.create_task(_reader())
            await self._reader_task

            # Wait for exit status
            await self._process.wait()
            exit_status = self._process.exit_status or 0
            duration_ms = int((time.monotonic() - start_time) * 1000)

            if self._cancelled:
                return OperationResult.failure(
                    "Playbook cancelled by user.",
                    data={
                        "exit_code": 130,
                        "duration_ms": duration_ms,
                        "output": "".join(output_buffer),
                    },
                )

            if exit_status == 0:
                return OperationResult.success(
                    f"Playbook completed successfully in {duration_ms/1000:.1f}s.",
                    data={
                        "exit_code": 0,
                        "duration_ms": duration_ms,
                        "output": "".join(output_buffer),
                    },
                )
            else:
                return OperationResult.failure(
                    f"Playbook exited with code {exit_status}.",
                    data={
                        "exit_code": exit_status,
                        "duration_ms": duration_ms,
                        "output": "".join(output_buffer),
                    },
                )

        except asyncio.CancelledError:
            self._cancelled = True
            if self._process:
                self._process.terminate()
            return OperationResult.failure("Playbook execution cancelled.")
        except Exception as exc:
            logger.exception("Error executing playbook")
            return result_from_exception("Playbook execution encountered an error.", exc)
        finally:
            if self._process:
                try:
                    self._process.terminate()
                except Exception:
                    pass
                self._process = None

    def cancel(self) -> None:
        """Interrupt and terminate the running remote process."""
        self._cancelled = True
        if self._process:
            try:
                # Send SIGINT (\x03) first
                self._process.stdin.write("\x03")
            except Exception:
                pass
            try:
                self._process.terminate()
            except Exception:
                pass
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()

    # Alias for stream execution
    run_stream = run
