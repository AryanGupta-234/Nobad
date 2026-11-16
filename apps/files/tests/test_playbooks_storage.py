from __future__ import annotations

from datetime import datetime
import unittest

from core.playbooks_models import (
    PlaybookCategory,
    PlaybookExecutionRecord,
    PlaybookRecipe,
    PlaybookSafetyTier,
    PlaybookVariable,
)
from storage.app_data import AppDataService


class TestPlaybooksStorage(unittest.TestCase):
    def setUp(self) -> None:
        self.app_data = AppDataService.create(":memory:")

    def test_snippet_crud(self) -> None:
        with self.app_data.session_factory() as session:
            repo = self.app_data.playbooks(session)

            recipe = PlaybookRecipe(
                id="custom-test-1",
                title="Restart Backend Pods",
                category=PlaybookCategory.CUSTOM,
                safety=PlaybookSafetyTier.SAFE,
                safety_label="Safe",
                description="Restarts application backend daemon.",
                script_template="systemctl restart backend-api",
                variables=[
                    PlaybookVariable(key="SERVICE", label="Service Name", default_value="backend-api")
                ],
                steps=["Check status", "Restart unit", "Verify active"],
                is_prebundled=False,
                is_favorite=False,
            )

            # 1. Add
            repo.add_snippet(recipe)
            session.commit()

            # 2. Get
            loaded = repo.get_snippet("custom-test-1")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.title, "Restart Backend Pods")
            self.assertEqual(len(loaded.variables), 1)
            self.assertEqual(loaded.variables[0].key, "SERVICE")

            # 3. List
            snippets = repo.list_custom_snippets()
            self.assertEqual(len(snippets), 1)

            # 4. Toggle favorite
            new_fav = repo.toggle_favorite("custom-test-1")
            self.assertTrue(new_fav)
            session.commit()
            self.assertTrue(repo.get_snippet("custom-test-1").is_favorite)

            # 5. Delete
            deleted = repo.delete_snippet("custom-test-1")
            self.assertTrue(deleted)
            session.commit()
            self.assertIsNone(repo.get_snippet("custom-test-1"))

    def test_execution_history(self) -> None:
        with self.app_data.session_factory() as session:
            repo = self.app_data.playbooks(session)

            record = PlaybookExecutionRecord(
                id="hist-1",
                recipe_id="certbot-ssl",
                recipe_title="Renew Certbot SSL",
                profile_id="prof-123",
                started_at=datetime.now(),
                duration_ms=4200,
                exit_code=0,
                status="success",
                log_output="SSL Renewal complete. Exit 0.",
            )

            repo.record_execution(record)
            session.commit()

            history = repo.list_history()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].recipe_id, "certbot-ssl")
            self.assertEqual(history[0].exit_code, 0)
            self.assertIn("SSL Renewal", history[0].log_output)


if __name__ == "__main__":
    unittest.main()
