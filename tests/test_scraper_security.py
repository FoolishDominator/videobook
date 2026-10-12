"""Acquisition must never disable TLS validation to work around access errors."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import scraper


class ScraperSecurityTests(unittest.TestCase):
    def test_subtitle_fallback_keeps_certificate_verification(self):
        failure = subprocess.CompletedProcess([], 1, '', 'certificate verify failed')
        with patch.object(scraper.os.path, 'exists', return_value=False), \
                patch.object(scraper.os, 'makedirs'), \
                patch.object(scraper, '_ffmpeg_location', return_value=None), \
                patch.object(scraper.glob, 'glob', return_value=[]), \
                patch.object(scraper.subprocess, 'run', return_value=failure) as run, \
                patch('builtins.print'):
            with self.assertRaisesRegex(ValueError, 'certificate verify failed'):
                scraper.fetch_via_ytdlp('https://www.bilibili.com/video/BVsynthetic/')
        command = run.call_args.args[0]
        self.assertNotIn('--no-check-certificates', command)
        self.assertNotIn('--no-check-certificate', command)
