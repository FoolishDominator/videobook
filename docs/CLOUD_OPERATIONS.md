# Cloud operation and recovery

## Deployment status

This checkout is an agent-assisted workflow, not a permanently running URL webhook.
An assistant must inspect the source, write/review the notes, validate artifacts,
confirm the publication destination, and perform an authorized publication.
The Python CLI handles deterministic acquisition, capture, rendering and validation.

The cloud preparation used Python 3.12 and the locked `asr` extra. CPU support was
verified by importing faster-whisper/CTranslate2 and decoding synthetic WAV audio.
The ASR extra pins PyAV below 19 for faster-whisper 1.2.x compatibility and includes
SOCKS proxy support. Official model weights are downloaded on demand; actual
transcription quality and language still require a short sample for each source.

Windows and Linux cleanup dispatch is covered with synthetic fixtures. A real Linux
synthetic-trash smoke test failed safely because `/workspace/.Trash-1000` is
read-only; the synthetic source remained intact. Recoverable cleanup is therefore
not operational on this specific host through native Trash. Use the explicit project-local archive described below
in this environment; it does not access the denied system Trash location. Native
Windows Recycle Bin operation still needs a Windows host smoke test. Tests never
recycle actual user outputs.

## Environment

From the repository root on Linux:

```bash
UV_CACHE_DIR=/workspace/shared/uv-cache uv sync --locked --extra asr
.venv/bin/python src/pipeline.py --help
.venv/bin/python -m unittest discover -s tests
```

On Windows use `uv sync --locked --extra asr`, followed by `uv run python ...`,
or `.venv\Scripts\python.exe`. Do not copy a Linux virtual environment to Windows.

Browser selection is shared between setup, capture, and login utilities. Installed
Chrome is preferred, with Chromium as Linux fallback. An optional explicit path
can be supplied as `VIDEOBOOK_BROWSER_EXECUTABLE`; an invalid explicit path fails
instead of silently opening another browser/profile.

```bash
VIDEOBOOK_BROWSER_EXECUTABLE=/usr/bin/chromium .venv/bin/python src/capture_frames.py --setup-profile
```

The current shell environment rejects Chromium's local singleton socket with
`Operation not permitted`, including the reviewed elevated attempt. Consequently,
shell-launched interactive login and browser captures are **blocked here**, and
the actual browser integration suite is not passing. Do not change sandbox or
security settings to bypass this. A managed cloud browser, if separately available,
is a different capability; its state and supported login/capture/file-transfer
route must be checked before relying on it. A successful login there does not
prove this repository's `.capture-profile` is authenticated. Never copy credentials
or cookie databases between browsers without the required authorization and
supported secure workflow.

## Per-link workflow

1. Identify video, requested language and intended scope. For third-party URL-only
   content, produce an original concise learning summary with source attribution;
   do not deliver or publish a full transcript, translation, or near-verbatim book.
   The full correction/translation pipeline is reserved for material supplied by
   the user or owned, authorized, or permissively licensed for that use. A public
   video is not automatically permissively licensed. A file-exclusion switch does
   not inspect or authorize the prose in `book.md` or `book.html`.
2. Inspect existing task state before acquisition. For eligible full-book work,
   follow `.agents/skills/videobook/SKILL.md` and its acquisition instructions.
   For summary-only work, write original summary Markdown/HTML and review it;
   do not fabricate the full transcript/translation checkpoints to satisfy a test.
3. Prefer available platform subtitles. Treat access/login/network errors separately
   from evidence that subtitles do not exist. Preserve source and task recovery
   files privately; never include authentication data in output or Git commits.
4. Only for eligible material and verified absent subtitles, run a short CPU ASR
   sample before a full run. For English, for example:

   ```bash
   .venv/bin/python src/asr_transcript.py "VIDEO_URL" --device cpu --compute-type int8 --language en --sample-start 0 --sample-dur 180
   .venv/bin/python src/asr_transcript.py "VIDEO_URL" --device cpu --compute-type int8 --language en --restart
   ```

   Use `--restart` only for the first full run after the sample, not for resuming
   an interrupted full run. The default large-v3 model downloads on first use;
   allow for its disk use and CPU processing time. Shared model caches belong
   outside disposable task folders and must not be cleaned as task scratch.
5. Validate the actual Markdown/HTML/images and the applicable checkpoints. Use
   `pipeline.py serve VIDEO_ID` for a local preview and confirm its printed URL
   actually responds. A cloud localhost URL is not a user-accessible public link.
6. **Before every publication, ask the user to confirm the exact target repository,
   branch, public URL and content to be published.** Do not assume the existing
   Lessons site or a previously selected address is still the intended destination.
   The historical example is `FoolishDominator/FoolishDominator.GitHub.io`, `main`,
   `https://foolishdominator.github.io/lessons/`; it is not standing authorization.
7. After that confirmation, prepare the explicitly selected destination. For an
   original summary on a project Pages site, for example:

   ```bash
   .venv/bin/python src/publish.py VIDEO_ID --site-repo SITE_CHECKOUT --site-branch CONFIRMED_BRANCH --public-base-url https://OWNER.github.io/PROJECT/ --content-dir notes --exclude-transcripts
   ```

   The base URL maps to the repository root; this example puts notes beneath
   `/PROJECT/notes/`. Both destination arguments are required. This creates only
   a local publication branch. Do not copy the placeholder target or a previous
   target into a new publication without the user's confirmation. Full eligible
   transcript publication omits the exclusion switch only when explicitly within
   the confirmed content scope.

   Prepare only the requested note, inspect the complete Git diff and public file
   list, then publish through an authorized connected GitHub route. GitHub plugin
   access does not install shell Git credentials. Do not generate tokens, modify
   credential helpers, or attempt an authenticated shell push unless separately
   authorized. Never publish `.capture-profile`, cookies, raw acquisition files,
   task caches or secrets. Use transcript exclusion for original-summary runs.
8. Verify the expected remote revision and actual public note, index and resources.
   A successful commit/push is not proof of a completed Pages deployment. Monitor
   the authorized deployment until success or a specific actionable blocker.
9. Only after successful applicable validation, preview cleanup then apply. Full
   book cleanup requires valid checkpoints and is intentionally unavailable for
   unfinished/summary-only tasks without those checkpoints; preserve their files
   rather than manufacturing checkpoints or weakening the cleanup guard.

## Recoverable cleanup

```bash
.venv/bin/python src/cleanup.py VIDEO_ID
.venv/bin/python src/cleanup.py VIDEO_ID --apply
.venv/bin/python src/pipeline.py status VIDEO_ID --mode book
```

The default is a preview. Linux uses recoverable freedesktop Trash via Send2Trash;
Windows uses the existing native Recycle Bin implementation. No permanent-delete
fallback is permitted. If the host Trash directory is unavailable, retain the file
and report the error. On a normal Linux host, an approved writable
XDG data directory may be set before invoking cleanup;
keep this directory outside `output/`, preserve its `Trash/files` and `Trash/info`
recovery records, and do not empty it. The installed Send2Trash backend selects
mount-local Trash based on the HOME device, so changing XDG_DATA_HOME alone does
not solve this cloud host’s read-only mount-root restriction. Do not retry through
other filesystem routes to bypass that restriction. A partial batch failure can leave already
recycled files in Trash while the remaining files remain at their source paths.

### Explicit project-local archive for restricted hosts

This is an application recovery archive, not OS Trash and not an automatic fallback.
Files move by same-filesystem rename into `.recycle-archive/BATCH_ID/files/` with a
manifest recording original relative paths and UTC timestamps. The archive is
Git-ignored, is never purged automatically, and must be kept until recovery is no
longer needed. Unsafe paths, conflicts and cross-device moves fail closed.

```bash
.venv/bin/python src/cleanup.py VIDEO_ID --archive
.venv/bin/python src/cleanup.py VIDEO_ID --archive --apply
.venv/bin/python src/cleanup.py --restore-archive BATCH_ID
.venv/bin/python src/cleanup.py --restore-archive BATCH_ID --apply
```

For authorized disposable task scratch use `--scratch TASK_NAME --archive` with
optional `--apply`. Review the manifest and printed batch ID after partial errors.
No real video outputs were moved during cloud setup.

Do not clean the entire output directory, website checkout, environment, browser
profile or source repository. Do not apply cleanup to a real task during setup.

## Outstanding verification

- Supply the first video or a permitted local test source and choose summary vs.
  an eligible full-book workflow.
- Check a supported managed-browser route if the platform requires login; the
  shell's Chromium launch is currently blocked as described above.
- Confirm repository, branch and exact public address before publishing.
- Download/test the selected ASR model only if needed for eligible source material.
- Native Windows Recycle Bin and real online acquisition/capture are not validated.
- TLS verification remains enabled for acquisition; certificate failures must be
  diagnosed using trusted configuration, never bypassed with insecure flags.
