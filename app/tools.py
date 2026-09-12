"""Tools the assistant may call: web search (DuckDuckGo HTML, no API key) and page fetch.
Results are plain text and go into the transcript, so the backpack fills with them — that's the point."""
from __future__ import annotations
import html, json, re
import httpx

UA = "Mozilla/5.0 (ctxdemo; HacLab teaching demo)"
SEARCH_URL = "https://html.duckduckgo.com/html/"
MAX_RESULTS = 5
MAX_PAGE_CHARS = 2000

TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web. Use for anything current: weather, news, scores, prices, facts you are unsure of.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetch_page",
        "description": "Fetch a web page and return its text (first 2000 characters). Use after web_search when a snippet is not enough.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
]

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", s)
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", s))).strip()


def parse_ddg(page: str) -> list[dict]:
    out = []
    for m in re.finditer(r'(?s)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                         r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', page):
        out.append({"title": strip_html(m.group(2)), "url": html.unescape(m.group(1)), "snippet": strip_html(m.group(3))})
        if len(out) >= MAX_RESULTS:
            break
    return out


class Tools:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._c = httpx.Client(timeout=10, headers={"User-Agent": UA}, follow_redirects=True, transport=transport)

    def web_search(self, query: str) -> str:
        r = self._c.post(SEARCH_URL, data={"q": query})
        r.raise_for_status()
        res = parse_ddg(r.text)
        if not res:
            return f"No results for: {query}"
        return "\n".join(f"{i+1}. {x['title']}\n   {x['url']}\n   {x['snippet']}" for i, x in enumerate(res))

    def fetch_page(self, url: str) -> str:
        r = self._c.get(url)
        r.raise_for_status()
        return strip_html(r.text)[:MAX_PAGE_CHARS]

    def run(self, name: str, arguments: str | dict) -> str:
        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        try:
            if name == "web_search":
                return self.web_search(str(args.get("query", "")))
            if name == "fetch_page":
                return self.fetch_page(str(args.get("url", "")))
            return f"unknown tool {name}"
        except Exception as e:  # the model gets the error as text, the turn continues
            return f"tool error: {type(e).__name__}: {e}"
