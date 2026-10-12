"""Regression checks for browser-only capture and retries."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import capture_frames


class DedicatedCaptureTests(unittest.TestCase):
    def test_incomplete_headless_capture_retries_headful(self):
        with tempfile.TemporaryDirectory() as profile:
            (Path(profile) / 'initialized').touch()
            images = Path(profile) / 'images'
            images.mkdir()
            with patch('playwright.sync_api.sync_playwright', return_value=MagicMock()), \
                    patch.object(capture_frames, '_run_capture', side_effect=[False, True]) as run:
                error = capture_frames.try_dedicated([], str(images), profile, 'video', 'youtube')
        self.assertIsNone(error)
        self.assertEqual([call.args[-1] for call in run.call_args_list], [True, False],
                         'Missing headless frames must retry in a browser before suggesting a download')

    def test_all_incomplete_attempts_are_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as profile:
            (Path(profile) / 'initialized').touch()
            images = Path(profile) / 'images'
            images.mkdir()
            with patch('playwright.sync_api.sync_playwright', return_value=MagicMock()), \
                    patch.object(capture_frames, '_run_capture', return_value=False):
                error = capture_frames.try_dedicated([], str(images), profile, 'video', 'youtube')
        self.assertIsNotNone(error, 'An incomplete browser capture cannot be reported as success')


if __name__ == '__main__':
    unittest.main()
