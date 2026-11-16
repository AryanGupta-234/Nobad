from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from core.playbooks_manager import PREBUNDLED_RECIPES, PlaybookStreamingRunner, interpolate_template
from core.playbooks_models import (
    PlaybookCategory,
    PlaybookExecutionRecord,
    PlaybookRecipe,
    PlaybookSafetyTier,
    PlaybookVariable,
)


class TestPlaybooksManager(unittest.IsolatedAsyncioTestCase):
    def test_prebundled_recipes_inventory(self) -> None:
        self.assertGreaterEqual(len(PREBUNDLED_RECIPES), 7)
        ids = {r.id for r in PREBUNDLED_RECIPES}
        self.assertIn("certbot-ssl", ids)
        self.assertIn("clean-disk", ids)
        self.assertIn("check-ports", ids)
        self.assertIn("docker-prune", ids)
        self.assertIn("pg-vacuum", ids)
        self.assertIn("nginx-reload", ids)
        self.assertIn("diagnostic-bundle", ids)

        for r in PREBUNDLED_RECIPES:
            self.assertTrue(r.is_prebundled)
            self.assertTrue(r.title)
            self.assertTrue(r.description)
            self.assertTrue(r.script_template)
            self.assertGreaterEqual(len(r.steps), 2)
            self.assertIn(r.safety, (PlaybookSafetyTier.SAFE, PlaybookSafetyTier.SUDO, PlaybookSafetyTier.DESTRUCTIVE))

    def test_interpolate_template(self) -> None:
        template = "certbot renew --cert-name {{DOMAIN}} {{#if DRY_RUN}}--dry-run{{/if}} && systemctl reload {{RELOAD_SERVICE}}"
        
        # 1. With DRY_RUN true
        rendered1 = interpolate_template(
            template,
            {"DOMAIN": "example.com", "DRY_RUN": "true", "RELOAD_SERVICE": "nginx"}
        )
        self.assertIn("example.com", rendered1)
        self.assertIn("--dry-run", rendered1)
        self.assertIn("systemctl reload nginx", rendered1)

        # 2. With DRY_RUN false
        rendered2 = interpolate_template(
            template,
            {"DOMAIN": "api.domain.io", "DRY_RUN": "false", "RELOAD_SERVICE": "apache2"}
        )
        self.assertIn("api.domain.io", rendered2)
        self.assertNotIn("--dry-run", rendered2)
        self.assertIn("systemctl reload apache2", rendered2)

    async def test_streaming_runner_execution(self) -> None:
        mock_process = MagicMock()
        mock_process.stdout.read = AsyncMock(side_effect=[
            "[1/4] Running pre-flight check...\n",
            "[2/4] Renewing SSL...\n",
            "[3/4] Reloading web service...\n",
            ""
        ])
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.wait = AsyncMock()
        mock_process.exit_status = 0

        mock_raw_conn = MagicMock()
        mock_raw_conn.create_process = AsyncMock(return_value=mock_process)

        mock_conn = MagicMock()
        mock_conn.raw_connection = mock_raw_conn

        runner = PlaybookStreamingRunner(mock_conn)
        chunks: list[str] = []

        def on_chunk(chunk: str) -> None:
            chunks.append(chunk)

        result = await runner.run_stream("echo 'test'", on_chunk)
        self.assertTrue(result.ok)
        self.assertEqual(len(chunks), 3)
        self.assertIn("Renewing SSL", "".join(chunks))

    async def test_streaming_runner_cancellation(self) -> None:
        mock_process = MagicMock()
        # Slow reader
        async def slow_read(*args):
            await asyncio.sleep(0.5)
            return "chunk"
        mock_process.stdout.read = AsyncMock(side_effect=slow_read)
        mock_process.stdin.write = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.wait = AsyncMock()
        mock_process.exit_status = 130

        mock_raw_conn = MagicMock()
        mock_raw_conn.create_process = AsyncMock(return_value=mock_process)
        mock_conn = MagicMock()
        mock_conn.raw_connection = mock_raw_conn

        runner = PlaybookStreamingRunner(mock_conn)

        async def cancel_soon():
            await asyncio.sleep(0.05)
            runner.cancel()

        cancel_task = asyncio.create_task(cancel_soon())
        result = await runner.run_stream("sleep 10", lambda c: None)
        await cancel_task

        self.assertFalse(result.ok)
        self.assertTrue(runner._cancelled)
        mock_process.stdin.write.assert_called_with("\x03")


if __name__ == "__main__":
    unittest.main()
