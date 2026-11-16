import os
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox"
import unittest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


class TestResponsiveWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()

    def test_window_minimum_size_floor(self) -> None:
        min_size = self.window.minimumSize()
        self.assertLessEqual(min_size.width(), 1024)
        self.assertLessEqual(min_size.height(), 600)

    def test_window_resizes_to_laptop_resolution_1366x720(self) -> None:
        self.window.resize(1366, 720)
        self.window.show()
        self.app.processEvents()
        self.assertEqual(self.window.width(), 1366)
        self.assertEqual(self.window.height(), 720)

    def test_window_resizes_to_compact_resolution_1024x600(self) -> None:
        self.window.resize(1024, 600)
        self.window.show()
        self.app.processEvents()
        self.assertEqual(self.window.width(), 1024)
        self.assertEqual(self.window.height(), 600)

    def test_all_workspace_pages_fit_1368x768_bounds(self) -> None:
        self.window.show()
        for name, page in self.window._pages.items():
            self.window.workspace.setCurrentWidget(page)
            self.window.resize(1366, 720)
            self.app.processEvents()

            # Window dimensions must hold cleanly without popping over 1366x720
            self.assertEqual(
                self.window.width(), 1366, f"Window width exceeded 1366 on page {name}"
            )
            self.assertEqual(
                self.window.height(), 720, f"Window height exceeded 720 on page {name}"
            )

            # Minimum size hint of active page must not exceed workarea height (720px)
            pmsh = page.minimumSizeHint()
            self.assertLess(
                pmsh.height(), 720, f"Page {name} minimumSizeHint height {pmsh.height()} exceeds 720px"
            )


if __name__ == "__main__":
    unittest.main()
