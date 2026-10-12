# Cloud preparation validation

Base revision: `35c6d655695aa11a97e74bd442d4a8524806e4a7`

## Passed

- 85 non-browser tests covering workflow, preview HTTP responses, publication,
  cleanup/archive/restore, browser selection, TLS verification policy and real
  faster-whisper decoding of a synthetic WAV.
- `python -m compileall -q src tests`
- `uv lock --check` and locked environment installation with the ASR extra.
- `git diff --check`
- CPU faster-whisper/CTranslate2 imports and supported int8 compute type.
- CLI smoke checks for pipeline, acquisition, ASR and capture.

Reproduce the tested non-browser suite from the repository root:

```bash
uv run --extra asr python -m unittest discover -s tests -p test_asr_runtime.py
uv run python -m unittest discover -s tests -p test_browser_config.py
uv run python -m unittest discover -s tests -p test_capture_frames.py
uv run python -m unittest discover -s tests -p test_cleanup.py
uv run python -m unittest discover -s tests -p test_workflow.py
uv run python -m unittest discover -s tests -p test_publish.py
uv run python -m unittest discover -s tests -p test_scraper_security.py
```

## Blocked or not run

- The real offline Chromium video suite cannot launch in this cloud shell:
  Chromium's singleton socket returns `Operation not permitted`. The reviewed
  elevated attempt had the same restriction. This is a failed integration setup,
  not a passing or deliberately skipped browser test. No bypass is implemented.
- Native Linux Trash is read-only at this host's mount root. A synthetic smoke
  attempt failed closed and retained the source. Explicit project-local archive
  and restore passed actual synthetic same-filesystem move tests instead.
- Windows dispatch is mocked; native Windows Recycle Bin execution was not run.
- A first public-audio trial exposed PyAV 19 incompatibility with faster-whisper
  1.2.1; the ASR extra now locks compatible PyAV 18.1.0 and SOCKS support. Official
  small-model download succeeded; a 90-second English audio sample completed on
  CPU int8 in 20.9 seconds. Full-video transcription quality is separate from the
  passing decoder/sample checks and still needs source-specific review.
- No video-platform login, authenticated capture, or GitHub Pages deployment.
- No real user outputs were cleaned, archived or restored in tests.

Use `python -m unittest discover -s tests` for the complete suite on a host where
installed Chrome/Chromium is permitted to launch. The browser suite uses a generated
local video fixture and does not request an online copyrighted video.
