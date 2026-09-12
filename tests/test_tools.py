import httpx
from app.tools import Tools, parse_ddg, strip_html

DDG = '''<div class="result"><h2><a rel="nofollow" class="result__a" href="https://weather.example/spokane">Spokane <b>Weather</b></a></h2>
<a class="result__snippet" href="https://weather.example/spokane">Sunny, high of <b>71</b>&deg;F.</a></div>
<div class="result"><h2><a class="result__a" href="https://other.example/">Other</a></h2><a class="result__snippet" href="x">second snippet</a></div>'''


def test_parse_ddg():
    r = parse_ddg(DDG)
    assert r[0] == {"title": "Spokane Weather", "url": "https://weather.example/spokane", "snippet": "Sunny, high of 71 °F."}
    assert len(r) == 2


def test_strip_html_drops_scripts():
    assert strip_html("<p>hi<script>x=1</script> <b>there</b></p>") == "hi there"


def test_search_and_fetch_via_transport():
    def handler(req: httpx.Request):
        if req.url.host == "html.duckduckgo.com":
            assert b"q=spokane+weather" in req.content
            return httpx.Response(200, text=DDG)
        return httpx.Response(200, text="<html><body><h1>Page</h1>" + "word " * 1000 + "</body></html>")
    t = Tools(transport=httpx.MockTransport(handler))
    out = t.run("web_search", '{"query": "spokane weather"}')
    assert out.startswith("1. Spokane Weather\n   https://weather.example/spokane\n   Sunny")
    page = t.run("fetch_page", {"url": "https://other.example/"})
    assert page.startswith("Page word") and len(page) <= 2000


def test_tool_errors_become_text():
    def handler(req): return httpx.Response(500)
    t = Tools(transport=httpx.MockTransport(handler))
    assert t.run("web_search", '{"query": "x"}').startswith("tool error:")
    assert t.run("nope", "{}") == "unknown tool nope"
