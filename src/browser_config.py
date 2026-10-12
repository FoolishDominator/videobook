"""Use one installed Chrome/Chromium executable for login and capture."""
import os
import shutil
import sys
from pathlib import Path


def find_chrome_exe():
    """Honor an explicit executable, then prefer Chrome over Chromium."""
    configured = os.environ.get("VIDEOBOOK_BROWSER_EXECUTABLE")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise ValueError(f"VIDEOBOOK_BROWSER_EXECUTABLE does not exist: {path}")
        return str(path.resolve())
    candidates = []
    if sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                candidates.append(Path(base) / "Google/Chrome/Application/chrome.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            executable = shutil.which(name)
            if executable:
                return executable
    return next((str(path) for path in candidates if path.is_file()), None)


def browser_launch_options():
    executable = find_chrome_exe()
    if not executable:
        raise OSError("Install Chrome/Chromium or set VIDEOBOOK_BROWSER_EXECUTABLE")
    return {"executable_path": executable}
