"""Real headless-browser test; skipped when Chromium isn't installed."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.crawler.renderer import PlaywrightRenderer, looks_js_rendered
from app.crawler.security import UrlGuard
from app.extraction.pipeline import ExtractionPipeline
from tests.helpers import make_settings

PARAS = "".join(
    f"<p>Paragraph {i}: emergency crews restored power to most neighbourhoods after the overnight storm, officials said.</p>"
    for i in range(12)
)
SHELL = f"""<html><head><title>Loading</title></head><body><div id="root"></div>
<script>
document.getElementById('root').innerHTML = '<article><h1>Power restored after storm</h1>{PARAS}</article>';
fetch('http://169.254.169.254/latest/meta-data').catch(() => {{}});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = SHELL.encode()
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_js_shell_heuristic():
    assert looks_js_rendered(SHELL, extracted_words=0, min_words=120)
    assert not looks_js_rendered(SHELL, extracted_words=500, min_words=120)


async def test_render_js_page(server):
    pytest.importorskip("playwright")
    port = int(server.rsplit(":", 1)[1])
    settings = make_settings(playwright_enabled=True, allowed_ports=[port])


    class TestServerOnlyGuard(UrlGuard):
        """Allow the loopback test server; everything else goes through the normal SSRF checks."""

        async def check(self, url):
            if url.startswith(server):
                return
            await super().check(url)

    from app.metrics import RENDER_TOTAL

    blocked = RENDER_TOTAL.labels("blocked_subrequest")
    before = blocked._value.get()
    renderer = PlaywrightRenderer(settings, guard=TestServerOnlyGuard())
    try:
        try:
            final_url, html = await renderer.render(server + "/story")
        except Exception as exc:  # pragma: no cover - environment without browsers
            pytest.skip(f"chromium unavailable: {exc}")
    finally:
        await renderer.aclose()
    assert "Power restored after storm" in html
    assert blocked._value.get() == before + 1  # the page's fetch() to the metadata IP was aborted
    report = await ExtractionPipeline().run(final_url, html)
    assert report.article.title == "Power restored after storm"
    assert report.article.word_count > 100


async def test_render_blocks_private_subrequests():
    renderer = PlaywrightRenderer(make_settings(), guard=UrlGuard())
    from app.crawler.security import BlockedURLError

    with pytest.raises(BlockedURLError):
        await renderer.render("http://127.0.0.1/")
    await renderer.aclose()
