"""Deterministic installed-browser selection, without opening a profile."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import browser_config


class BrowserConfigTests(unittest.TestCase):
    def test_explicit_path_used_consistently(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "browser with spaces"
            executable.touch()
            with patch.dict(os.environ, {"VIDEOBOOK_BROWSER_EXECUTABLE": str(executable)}):
                self.assertEqual(browser_config.browser_launch_options(), {"executable_path": str(executable.resolve())})

    def test_bad_explicit_path_does_not_silently_switch_browser(self):
        with patch.dict(os.environ, {"VIDEOBOOK_BROWSER_EXECUTABLE": "/nonexistent/videobook-browser"}):
            with self.assertRaises(ValueError):
                browser_config.browser_launch_options()

    def test_linux_chromium_fallback(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(browser_config.sys, "platform", "linux"), patch.object(browser_config.shutil, "which", side_effect=lambda name: "/usr/bin/chromium" if name == "chromium" else None):
            self.assertEqual(browser_config.find_chrome_exe(), "/usr/bin/chromium")

    def test_missing_browser_fails_clearly(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(browser_config.sys, "platform", "linux"), patch.object(browser_config.shutil, "which", return_value=None):
            with self.assertRaises(OSError):
                browser_config.browser_launch_options()
