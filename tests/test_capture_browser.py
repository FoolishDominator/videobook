"""Offline Chrome regression tests with a generated, local video fixture."""
import base64
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import capture_frames


class BoundedPage:
    """Shorten failed waits; leave the real navigation/capture path intact."""
    def __init__(self, page):
        self.page = page

    def __getattr__(self, name):
        return getattr(self.page, name)

    def goto(self, url, **options):
        return self.page.goto(url, **{**options, 'timeout': 1000})

    def evaluate(self, function, arg=None):
        return self.page.evaluate('''async ({source, argument}) => Promise.race([
            (eval('(' + source + ')'))(argument),
            new Promise((_,reject)=>setTimeout(()=>reject(new Error('Video operation did not settle')),1500))
        ])''', {'source': function, 'argument': arg})


@unittest.skipUnless(capture_frames.find_chrome_exe(), 'Chrome is required for offline video-rendering tests')
class BrowserCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import imageio_ffmpeg
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        video = cls.root / 'fixture.webm'
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-f', 'lavfi',
                        '-i', 'testsrc2=size=320x240:rate=25', '-t', '3', '-c:v', 'libvpx',
                        '-b:v', '400k', str(video)], check=True, capture_output=True)
        data = base64.b64encode(video.read_bytes()).decode()
        cls.html = ('<style>body{margin:0}video{width:640px;height:480px}</style>'
                    '<video muted autoplay loop src="data:video/webm;base64,' + data + '"></video>')
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel='chrome', headless=True,
                           ignore_default_args=['--hide-scrollbars'],
                           args=['--autoplay-policy=no-user-gesture-required'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(self.context.close)
        self.pending_routes = []
        self.addCleanup(lambda: [route.abort() for route in self.pending_routes])
        self.page = self.context.new_page()
        self.page.set_default_timeout(1500)
        self.images = self.root / 'images'
        self.images.mkdir(exist_ok=True)

    def route(self, path, html):
        self.context.route('https://capture.test/' + path,
                           lambda route: route.fulfill(body=html, content_type='text/html; charset=utf-8'))

    def shoot(self, name, urls):
        with patch.object(capture_frames, 'READY_TIMEOUT_MS', 600, create=True):
            return capture_frames._shoot(BoundedPage(self.page), 1, name, str(self.images), urls)

    def test_playable_video_does_not_wait_for_unrelated_document_script(self):
        self.route('slow', self.html + '<script src="https://capture.test/hang.js"></script>')
        self.context.route('https://capture.test/hang.js', lambda route: self.pending_routes.append(route))
        self.assertTrue(self.shoot('slow', ['https://capture.test/slow']),
                        'A decoded video must remain capturable when document loading is unfinished')

    def test_screenshot_uses_decoded_video_size_instead_of_css_upscale(self):
        self.route('native', self.html)
        (self.images / 'native.png').write_bytes(b'previous image')
        self.assertTrue(self.shoot('native', ['https://capture.test/native']))
        header = (self.images / 'native.png').read_bytes()[:24]
        self.assertEqual(struct.unpack('>II', header[16:24]), (320, 240))
        state = self.page.locator('video').evaluate('(v)=>({time:v.currentTime,paused:v.paused})')
        self.assertTrue(state['paused'])
        self.assertAlmostEqual(state['time'], 1, places=2)
        backups = list((self.root / '_capture_backups').glob('*/native.png'))
        self.assertTrue(any(path.read_bytes() == b'previous image' for path in backups))

    def test_unplayable_embed_retries_the_watch_page(self):
        self.route('empty', '<video muted></video>')
        self.route('watch', self.html)
        self.assertTrue(self.shoot('retry', ['https://capture.test/empty', 'https://capture.test/watch']))
        self.assertEqual(self.page.url, 'https://capture.test/watch')

    def test_youtube_chooses_highest_enabled_quality_not_auto(self):
        self.route('quality', self.html + '''
            <button class="ytp-settings-button" onclick="document.querySelector('#settings').hidden=false">Settings</button>
            <div class="ytp-panel-menu" id="settings" hidden>
                <button class="ytp-menuitem" onclick="document.querySelector('#quality').hidden=false">画质 自动 (144p)</button>
            </div>
            <div class="ytp-panel-menu" id="quality" hidden>
                <button role="menuitemradio" aria-disabled="true">1080p</button>
                <button role="menuitemradio" onclick="this.setAttribute('aria-checked','true')">240p</button>
                <button role="menuitemradio">144p</button>
                <button role="menuitemradio">自动</button>
            </div>''')
        self.page.goto('https://capture.test/quality')
        capture_frames._wait_for_video(self.page)
        quality = capture_frames._select_youtube_quality(self.page)
        self.assertEqual(quality['selected'], '240p')
        self.assertEqual(quality['available'], ['240p', '144p'])
        self.assertEqual(self.page.get_by_role('menuitemradio', name='240p').get_attribute('aria-checked'), 'true')

    def test_seeking_the_same_paused_frame_does_not_wait_forever(self):
        self.route('same-time', self.html)
        self.page.goto('https://capture.test/same-time')
        capture_frames._wait_for_video(self.page)
        capture_frames._seek_frame(self.page, 1)
        state = capture_frames._seek_frame(self.page, 1)
        self.assertEqual(state['time'], 1)
        self.assertTrue(state['paused'])

    def test_player_overlay_cannot_override_screenshot_mask(self):
        self.route('overlay', self.html)
        self.page.goto('https://capture.test/overlay')
        capture_frames._wait_for_video(self.page)
        state = capture_frames._seek_frame(self.page, 1)
        baseline, masked = self.root / 'unobstructed.png', self.root / 'masked.png'
        capture_frames._native_screenshot(self.page, baseline, state)
        self.page.evaluate('''() => {
            const style=document.createElement('style');
            style.textContent='.player-overlay { visibility:visible!important; position:fixed; left:100px; top:100px; width:20px; height:20px; background:red; z-index:2147483647; }';
            document.head.append(style);
            const overlay=document.createElement('div');
            overlay.className='player-overlay'; document.body.append(overlay);
            // Named form fields can shadow the element.style property.
            const form=document.createElement('form');
            form.innerHTML='<input name="style">'; document.body.append(form);
        }''')
        capture_frames._native_screenshot(self.page, masked, state)
        self.assertEqual(masked.read_bytes(), baseline.read_bytes(),
                         'Player controls with explicit visibility must not appear over decoded pixels')

    def test_page_scrollbars_are_not_part_of_the_video_frame(self):
        self.route('overflow', self.html)
        self.page.goto('https://capture.test/overflow')
        capture_frames._wait_for_video(self.page)
        state = capture_frames._seek_frame(self.page, 1)
        baseline, overflowing = self.root / 'no-scroll.png', self.root / 'overflow.png'
        capture_frames._native_screenshot(self.page, baseline, state)
        self.page.evaluate('''() => { const content=document.createElement('div');
            content.style.cssText='width:2000px;height:2000px'; document.body.append(content); }''')
        capture_frames._native_screenshot(self.page, overflowing, state)
        self.assertEqual(overflowing.read_bytes(), baseline.read_bytes(),
                         'Page scrollbars must not cover the video in visible Chrome')


if __name__ == '__main__':
    unittest.main()
