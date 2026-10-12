"""Capture the platform player's decoded video directly, without media downloads.

Usage:
    python capture_frames.py --setup-profile
    python capture_frames.py <video_id> [video_url] [--method auto|dedicated]
                             [--materialize-only] [--profile-dir PATH] [--recapture]

Uses a dedicated Chrome profile and records quality, decoded size, exact time,
and failures in capture.json. Workflow and fallback policy live in
.agents/skills/videobook/references/capture.md.
"""
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from extract_frames import materialize

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROFILE_DIR = os.path.join(BASE_DIR, ".capture-profile")

# Hide player chrome while preserving the original video element.
HIDE_CSS = ("body *{visibility:hidden!important}"
            "video, video *{visibility:visible!important}")

# A size threshold flags suspicious frames; visual review remains necessary.
MIN_SHOT_BYTES = 10000
READY_TIMEOUT_MS = 30000
SEEK_TIMEOUT_MS = 15000

VIDEO_STATE = """() => {
    const v = document.querySelector('video');
    return v ? {width:v.videoWidth, height:v.videoHeight, time:v.currentTime,
        ready:v.readyState, paused:v.paused, seeking:v.seeking,
        error:v.error ? v.error.message : null,
        advertisement:!!document.querySelector('.ad-showing, .ad-interrupting')} : null;
}"""


def detect_platform(video_id: str, video_url: str) -> str:
    if video_url:
        if "youtube.com" in video_url or "youtu.be" in video_url:
            return "youtube"
        if "bilibili.com" in video_url:
            return "bilibili"
    if video_id.startswith("BV"):
        return "bilibili"
    return ""


def build_url(platform: str, video_id: str, sec: int) -> str:
    if platform == "bilibili":
        return (f"https://player.bilibili.com/player.html?bvid={video_id}"
                f"&t={sec}&autoplay=1&high_quality=1&danmaku=0")
    return f"https://www.youtube.com/embed/{video_id}?start={sec}&autoplay=1"


def build_main_url(platform: str, video_id: str, sec: int) -> str:
    """D 层兜底页面：主站观看页。"""
    if platform == "bilibili":
        return f"https://www.bilibili.com/video/{video_id}/?t={sec}"
    return f"https://www.youtube.com/watch?v={video_id}&t={sec}s"


def parse_timestamps(source_md: str):
    with open(source_md, encoding="utf-8") as f:
        content = f.read()
    return sorted(set(re.findall(r"SCREENSHOT:(\d{2}:\d{2}:\d{2})", content)))


def shots_spec(timestamps, platform, video_id):
    """Build [seconds, image-name, embed-url, main-url] rows."""
    shots = []
    for ts in timestamps:
        h, m, s = (int(x) for x in ts.split(":"))
        sec = h * 3600 + m * 60 + s
        shots.append([sec, "shot_" + ts.replace(":", "_"),
                      build_url(platform, video_id, sec),
                      build_main_url(platform, video_id, sec)])
    return shots


def frames_missing(timestamps, imgdir):
    return [ts for ts in timestamps
            if not os.path.exists(os.path.join(imgdir, "shot_" + ts.replace(":", "_") + ".png"))]


def find_chrome_exe():
    candidates = []
    if sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/Google Chrome.app/Contents/Google Chrome")
    else:
        import shutil
        for name in ("google-chrome", "google-chrome-stable"):
            exe = shutil.which(name)
            if exe:
                return exe
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def setup_profile(profile_dir: str, open_url: str = "https://www.bilibili.com") -> None:
    """One-time init: open Chrome with the dedicated profile for manual login."""
    exe = find_chrome_exe()
    if not exe:
        sys.exit("Chrome executable not found")
    os.makedirs(profile_dir, exist_ok=True)
    print("opening Chrome with the dedicated capture profile ...")
    print("log in to the platforms you need (bilibili / YouTube) in that window,")
    print("then CLOSE the window to finish setup.")
    subprocess.run([exe, f"--user-data-dir={profile_dir}", open_url])
    print("setup finished; cookies are persisted in", profile_dir)


# ─────────────────────────────────────────────
# Player capture internals
# ─────────────────────────────────────────────

def _force_top_quality(page):
    """C 层：拦截 playurl，只留顶档最高码率变体（优先 AVC 兼容性）。"""
    def handle(route):
        resp = route.fetch()
        try:
            j = resp.json()
            vids = j["data"]["dash"]["video"]
            top = max(v["id"] for v in vids)
            cands = [v for v in vids if v["id"] == top]
            avc = [v for v in cands if v["codecs"].startswith("avc")] or cands
            j["data"]["dash"]["video"] = [max(avc, key=lambda v: v["bandwidth"])]
            route.fulfill(response=resp, json=j)
        except Exception:
            route.fulfill(response=resp)
    page.route("**/*playurl*", handle)


def _probe_native_size(page, video_id):
    """B 层：查询顶档原生分辨率 [w,h]，用于 1:1 viewport。"""
    try:
        return page.evaluate("""async (bvid) => {
            const cid = (await (await fetch('https://api.bilibili.com/x/web-interface/view?bvid=' + bvid)).json()).data.cid;
            const d = (await (await fetch('https://api.bilibili.com/x/player/playurl?bvid=' + bvid + '&cid=' + cid + '&qn=120&fnval=4048', {credentials:'include'})).json()).data;
            const vids = ((d || {}).dash || {}).video || [];
            if (!vids.length) return null;
            const top = Math.max.apply(null, vids.map(v => v.id));
            const v = vids.filter(x => x.id === top).sort((a, b) => b.bandwidth - a.bandwidth)[0];
            return [v.width, v.height];
        }""", video_id)
    except Exception:
        return None


def _wait_for_video(page):
    """Wait on decoded video, not unrelated scripts blocking DOMContentLoaded."""
    page.wait_for_selector("video", state="attached", timeout=READY_TIMEOUT_MS)
    page.evaluate("""() => { const v=document.querySelector('video');
        v.muted=true; v.play().catch(()=>{}); }""")
    page.wait_for_function("""() => { const v=document.querySelector('video');
        return v && (v.error || (v.readyState>=2 && v.videoWidth>0 &&
            !document.querySelector('.ad-showing, .ad-interrupting'))); }""",
        timeout=READY_TIMEOUT_MS)
    state = page.evaluate(VIDEO_STATE)
    if state["error"]:
        raise RuntimeError("Video decoder: " + state["error"])
    return state


def _select_youtube_quality(page):
    """Choose the highest enabled resolution in the actual player menu."""
    page.locator("video").hover()
    page.locator(".ytp-settings-button").click(timeout=10000)
    page.locator(".ytp-panel-menu:visible .ytp-menuitem").filter(
        has_text=re.compile(r"画质|畫質|清晰度|Quality", re.I)).click(timeout=10000)
    options = page.locator('.ytp-panel-menu:visible [role="menuitemradio"]')
    options.first.wait_for(state="visible", timeout=10000)
    choices = options.evaluate_all("""items => items.map((item,index)=>({
        index, label:item.innerText.trim(), disabled:item.getAttribute('aria-disabled')==='true'
    }))""")
    available = []
    for item in choices:
        resolution = re.search(r"(\d{3,4})\s*p", item["label"], re.I)
        if resolution and not item["disabled"]:
            available.append({**item, "height": int(resolution.group(1))})
    if not available:
        raise RuntimeError("YouTube did not expose selectable quality levels")
    selected = max(available, key=lambda item: item["height"])
    options.nth(selected["index"]).click(timeout=10000)
    # Keep playing until the decoder has switched, then seek/pause for capture.
    page.wait_for_function("""height => { const v=document.querySelector('video');
        return v && v.readyState>=2 && Math.min(v.videoWidth,v.videoHeight)>=height;
    }""", arg=selected["height"], timeout=READY_TIMEOUT_MS)
    return {"selected": selected["label"], "height": selected["height"],
            "available": [item["label"] for item in available]}


def _seek_frame(page, sec):
    """Bound every wait; install listeners before seeking; wait for decoded paint."""
    page.evaluate("""async ({target, timeout}) => {
        const v=document.querySelector('video');
        if (!v || v.error) throw new Error('Video is unavailable');
        if (!Number.isFinite(v.duration) || target<0 || target>=v.duration)
            throw new Error('Timestamp is outside the video');
        v.muted=true; v.pause();
        const seekNeeded=Math.abs(v.currentTime-target)>0.01 || v.seeking;
        await new Promise((resolve,reject)=>{
            let frame=null, interval=null, timer=null, painted=!seekNeeded;
            const cleanup=()=>{ clearTimeout(timer); clearInterval(interval);
                v.removeEventListener('seeked',check); v.removeEventListener('error',failed);
                if(frame!==null) v.cancelVideoFrameCallback?.(frame); };
            const failed=()=>{cleanup();reject(new Error('Video decoder failed during seek'));};
            const check=()=>{
                if(v.error) return failed();
                if(!v.seeking && v.readyState>=2 && Math.abs(v.currentTime-target)<=0.01 && painted){
                    cleanup(); resolve();
                }
            };
            timer=setTimeout(()=>{cleanup();reject(new Error('Timed out waiting for target video frame'));},timeout);
            interval=setInterval(check,50);
            v.addEventListener('seeked',check); v.addEventListener('error',failed);
            if(seekNeeded && v.requestVideoFrameCallback){
                const onFrame=(_,meta)=>{
                    painted=Math.abs(meta.mediaTime-target)<0.15;
                    if(!painted) frame=v.requestVideoFrameCallback(onFrame);
                    check();
                };
                frame=v.requestVideoFrameCallback(onFrame);
            } else painted=true;
            if(seekNeeded) v.currentTime=target;
            check();
        });
        await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    }""", {"target": sec, "timeout": SEEK_TIMEOUT_MS})
    return page.evaluate(VIDEO_STATE)


def _native_screenshot(page, path, state):
    """Render the decoded pixels 1:1, without player controls or CSS upscaling."""
    width, height = state["width"], state["height"]
    page.set_viewport_size({"width": width, "height": height})
    page.add_style_tag(content=HIDE_CSS + """
        html,body { margin:0!important; overflow:hidden!important; }
        video { position:fixed!important; left:0!important; top:0!important;
            max-width:none!important; max-height:none!important; min-width:0!important;
            min-height:0!important; transform:none!important; object-fit:fill!important;
            border:0!important; border-radius:0!important; z-index:2147483647!important; }
        """ + f"video {{ width:{width}px!important; height:{height}px!important; }}")
    page.evaluate("""() => {
        const video=document.querySelector('video');
        const setStyle=(element,key,value)=>element.setAttribute('style',
            (element.getAttribute('style')||'')+';'+key+':'+value+'!important;');
        // Visibility can be overridden by a control's own !important rule.
        // Hide each sibling branch by opacity; children cannot opt back in.
        for(const element of document.querySelectorAll('body *')){
            if(element!==video && !element.contains(video))
                setStyle(element,'opacity','0');
        }
        for(let p=video.parentElement;p;p=p.parentElement){
            for(const [key,value] of Object.entries({overflow:'visible',transform:'none',
                    contain:'none','clip-path':'none',filter:'none','border-radius':'0'}))
                setStyle(p,key,value);
        }
        setStyle(document.documentElement,'overflow','hidden');
        setStyle(document.body,'overflow','hidden');
    }""")
    page.locator("video").screenshot(path=str(path), scale="css", timeout=10000)
    header = Path(path).read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", header[16:24]) != (width, height):
        raise RuntimeError("Screenshot dimensions do not match decoded video")


def _shoot(page, sec, name, imgdir, urls, platform="", report=None):
    """Try the entire capture on each page; retain originals until replacement is valid."""
    for url in urls:
        stage = "navigation"
        try:
            page.goto(url, wait_until="commit", timeout=45000)
            stage = "video readiness"
            _wait_for_video(page)
            stage = "highest quality"
            quality = _select_youtube_quality(page) if platform == "youtube" else None
            stage = "seek"
            state = _seek_frame(page, sec)
            if quality and min(state["width"], state["height"]) < quality["height"]:
                raise RuntimeError("Decoded resolution fell below selected quality")
            stage = "screenshot"
            with tempfile.TemporaryDirectory(prefix="capture_", dir=Path(imgdir).parent) as temp:
                pending = Path(temp) / (name + ".png")
                _native_screenshot(page, pending, state)
                if pending.stat().st_size < MIN_SHOT_BYTES:
                    # A small PNG is suspicious, but never silently change its timestamp.
                    state = _seek_frame(page, sec)
                    _native_screenshot(page, pending, state)
                    if pending.stat().st_size < MIN_SHOT_BYTES:
                        raise RuntimeError("Suspiciously small frame; visual inspection required")
                final_state = page.evaluate(VIDEO_STATE)
                if (not final_state["paused"] or abs(final_state["time"]-sec)>0.05
                        or [final_state["width"], final_state["height"]] != [state["width"], state["height"]]):
                    raise RuntimeError("Video changed during screenshot")
                destination = Path(imgdir) / (name + ".png")
                if destination.exists():
                    backup = Path(imgdir).parent / "_capture_backups" / str(time.time_ns())
                    backup.mkdir(parents=True)
                    shutil.copy2(destination, backup / destination.name)
                os.replace(pending, destination)
            if report is not None:
                report["frames"][name] = {"requested_seconds": sec, "actual_seconds": final_state["time"],
                    "decoded_size": [state["width"], state["height"]], "quality": quality,
                    "url": url, "method": "browser"}
            print(f"saved {name}.png: {state['width']}x{state['height']} at {final_state['time']:.3f}s", flush=True)
            return True
        except Exception as error:
            message = str(error).split("Call log:")[0].strip().splitlines()[0][:400]
            print(f"  {name}: {stage} failed on {urlsplit(url).path}: {message}", flush=True)
            if report is not None:
                report["attempts"].append({"frame": name, "url": url, "stage": stage, "error": message})
    return False


def _run_capture(p, shots, imgdir, profile_dir, video_id, platform, headless, report=None):
    ctx = p.chromium.launch_persistent_context(
        profile_dir, channel="chrome", headless=headless,
        viewport={"width": 1280, "height": 720},
        device_scale_factor=1,
        args=["--autoplay-policy=no-user-gesture-required"])
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if platform == "bilibili":
            _force_top_quality(page)
            page.goto("https://www.bilibili.com", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1000)
            dims = _probe_native_size(page, video_id)
            if dims:
                print(f">> native stream size: {dims[0]}x{dims[1]} (viewport 1:1)")
                page.set_viewport_size({"width": dims[0], "height": dims[1]})
        ok_all = True
        for sec, name, embed, main in shots:
            if report is not None and name in report["frames"]:
                continue
            # Direct YouTube embeds can reject an absent Referer (error 153).
            urls = [main, embed] if platform == "youtube" else [embed, main]
            if not _shoot(page, sec, name, imgdir, urls, platform, report):
                print("  warning: capture failed for", name)
                ok_all = False
            if report is not None:
                Path(imgdir).parent.joinpath("capture.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return ok_all
    finally:
        ctx.close()


def try_dedicated(shots, imgdir, profile_dir, video_id="", platform=""):
    """Retry incomplete headless captures in the dedicated visible Chrome."""
    if not os.path.isdir(profile_dir) or not os.listdir(profile_dir):
        return "unavailable: capture profile not initialized (run: python capture_frames.py --setup-profile)"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "unavailable: Playwright not installed (python -m pip install playwright)"
    last_err = None
    report = {"video_id": video_id, "platform": platform, "frames": {}, "attempts": [], "runs": []}
    for headless in (True, False):  # A 层：headless 优先，回退 headful
        run = {"headless": headless, "complete": False}
        report["runs"].append(run)
        try:
            with sync_playwright() as p:
                complete = _run_capture(p, shots, imgdir, profile_dir, video_id, platform, headless, report=report)
            run["complete"] = complete
            if complete:
                return None
            last_err = f"headless={headless} finished with missing frames"
        except Exception as e:
            last_err = f"headless={headless} failed: {e}"
            run["error"] = str(e).splitlines()[0][:400]
        finally:
            Path(imgdir).parent.joinpath("capture.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("  " + last_err, flush=True)
    return last_err


METHOD_ORDER = ["dedicated"]
METHOD_DESC = {
    "dedicated": "dedicated Chrome (highest available quality, native pixels, verified timestamp)",
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture frames directly from the platform player")
    ap.add_argument("video_id", nargs="?")
    ap.add_argument("video_url", nargs="?", default=None)
    ap.add_argument("--method", default="auto", choices=["auto"] + METHOD_ORDER)
    ap.add_argument("--materialize-only", action="store_true",
                    help="skip capture; materialize placeholders from existing images only")
    ap.add_argument("--setup-profile", action="store_true",
                    help="one-time: open Chrome with the dedicated profile to log in")
    ap.add_argument("--profile-dir", default=DEFAULT_PROFILE_DIR,
                    help="dedicated Chrome user-data-dir (default: <repo>/.capture-profile)")
    ap.add_argument("--recapture", action="store_true",
                    help="recapture all requested frames; preserve replaced images in _capture_backups/")
    args = ap.parse_args()

    if args.setup_profile:
        setup_profile(args.profile_dir)
        return

    if args.video_id:
        platform = detect_platform(args.video_id, args.video_url)
        if not platform:
            sys.exit("unsupported platform: pass the video url as 2nd arg")
    else:
        platform = ""

    if not args.video_id:
        ap.error("video_id is required (unless using --setup-profile)")

    vdir = os.path.join(BASE_DIR, "output", args.video_id)
    book = os.path.join(vdir, "book.md")
    tagged = os.path.join(vdir, "book.tagged.md")
    imgdir = os.path.join(vdir, "images")
    os.makedirs(imgdir, exist_ok=True)

    source_md = tagged if os.path.exists(tagged) else book
    if not os.path.exists(source_md):
        sys.exit("no book markdown found: " + source_md)
    timestamps = parse_timestamps(source_md)
    if not timestamps:
        sys.exit("no SCREENSHOT placeholders found in " + source_md)

    if args.materialize_only:
        missing = frames_missing(timestamps, imgdir)
        if missing:
            print("warning: missing frames for:", ", ".join(missing))
        materialize(book, tagged, imgdir)
        return

    missing = timestamps if args.recapture else frames_missing(timestamps, imgdir)
    if not missing:
        print("all frames present; nothing to capture")
        materialize(book, tagged, imgdir)
        return
    shots = shots_spec(missing, platform, args.video_id)
    print(f">> {len(missing)} frame(s) to capture")
    order = METHOD_ORDER if args.method == "auto" else [args.method]
    used = None
    for name in order:
        print(f"\n>>> trying [{name}] {METHOD_DESC[name]}")
        err = try_dedicated(shots, imgdir, args.profile_dir, args.video_id, platform)
        if err is None:
            missing = frames_missing(timestamps, imgdir)
            if not missing:
                used = name
                print(f"<<< [{name}] OK: captured {len(timestamps)} frames")
                break
            err = "finished but missing: " + ", ".join(missing)
        print(f"<<< [{name}] {err}")

    if used is None:
        sys.exit("\nAll browser capture methods failed. Use the fallback:\n"
                 f'  python extract_frames.py {args.video_id} "{args.video_url or ""}"')

    materialize(book, tagged, imgdir)


if __name__ == "__main__":
    main()
