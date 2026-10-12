"""Synthetic decode smoke test for the optional ASR dependency stack."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import wave


@unittest.skipUnless(importlib.util.find_spec('faster_whisper'), 'Install the asr extra')
class ASRRuntimeTests(unittest.TestCase):
    def test_faster_whisper_decodes_local_audio(self):
        # PyAV 19 removed a keyword still used by faster-whisper 1.2.x.
        # Exercise the real decoder without a model or external audio.
        from faster_whisper.audio import decode_audio
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.wav'
            with wave.open(str(path), 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(b'\0\0' * 1600)
            decoded = decode_audio(str(path), sampling_rate=16000)
            self.assertEqual(len(decoded), 1600)
            self.assertTrue((decoded == 0).all())
