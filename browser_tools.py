"""
Jarvis V2 — Web Tools
Background web search, page reading and news via plain HTTP requests (no visible browser).
Opening a URL for the user still uses their default browser.
"""

import asyncio
import re
import webbrowser
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import httpx

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")
PAGES_TO_READ = 3
CHARS_PER_PAGE = 2000
NEWS_FEEDS = {
    "Google News (India)": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    "BBC World": "https://feeds.bbci.co.uk/news/world/rss.xml",
}

_http = httpx.AsyncClient(timeout=8, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def _strip_html(html: str) -> str:
    """Readable text from a page: prefer <article>/<main>, drop scripts, menus and markup."""
    for tag in ("article", "main"):
        m = re.search(rf"<{tag}\b.*?</{tag}>", html, re.S | re.I)
        if m and len(m.group(0)) > 1500:
            html = m.group(0)
            break
    html = re.sub(r"<(script|style|noscript|svg|nav|header|footer|form|aside)\b.*?</\1>", " ", html, flags=re.S | re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", text).strip()


async def _read_page(url: str) -> str:
    try:
        r = await _http.get(url)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        return _strip_html(r.text)[:CHARS_PER_PAGE]
    except Exception:
        return ""


async def search_web(query: str) -> str:
    """Search DuckDuckGo, read the top pages in parallel, and return snippets plus page text."""
    try:
        r = await _http.post("https://html.duckduckgo.com/html/", data={"q": query})
    except Exception as e:
        return f"FAILED: search error: {e}"

    # Each result is a title link followed by its snippet; pair each link with the snippet before the next link
    links = list(re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S))
    results = []
    for i, link in enumerate(links):
        url = unescape(link.group(1))
        if "uddg=" in url:  # DuckDuckGo redirect link: the real URL is in the uddg parameter
            url = unquote(parse_qs(urlparse(url).query)["uddg"][0])
        if "duckduckgo.com/y.js" in url:  # ads
            continue
        section_end = links[i + 1].start() if i + 1 < len(links) else len(r.text)
        snippet = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', r.text[link.end():section_end], re.S)
        results.append({
            "title": _strip_html(link.group(2)),
            "url": url,
            "snippet": _strip_html(snippet.group(1)) if snippet else "",
        })
        if len(results) == 6:
            break
    if not results:
        return f"FAILED: no search results (HTTP {r.status_code})"

    pages = await asyncio.gather(*(_read_page(res["url"]) for res in results[:PAGES_TO_READ]))
    out = [f"Web search results for: {query}"]
    for i, res in enumerate(results):
        out.append(f"\n[{i + 1}] {res['title']} ({urlparse(res['url']).netloc})\n{res['snippet']}")
        if i < len(pages) and pages[i]:
            out.append(f"Page text: {pages[i]}")
    return "\n".join(out)


async def visit(url: str) -> dict:
    """Read a URL's main text in the background."""
    text = await _read_page(url)
    if not text:
        return {"error": "page could not be read", "url": url}
    return {"title": urlparse(url).netloc, "url": url, "content": text}


async def fetch_news() -> str:
    """Current headlines from RSS feeds."""
    async def headlines(name, url):
        try:
            r = await _http.get(url)
            titles = re.findall(r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", r.text, re.S)
            return f"{name}:\n" + "\n".join(f"- {unescape(t).strip()}" for t in titles[:12])
        except Exception:
            return ""
    sections = [s for s in await asyncio.gather(*(headlines(n, u) for n, u in NEWS_FEEDS.items())) if s]
    if not sections:
        return "FAILED: news could not be loaded"
    return "Current headlines\n\n" + "\n\n".join(sections)


async def open_url(url: str):
    """Open URL in user's default browser (non-blocking)."""
    await asyncio.to_thread(webbrowser.open, url)
    return {"success": True, "url": url}
