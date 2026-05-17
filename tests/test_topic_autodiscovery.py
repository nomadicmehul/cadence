"""Tests for the RSS / Atom autodiscovery path in fetch_topics().

When a user pastes a page URL like https://dev.to/t/googlecloud (HTML, not
a feed), the fetcher should:
  1. Notice the response is HTML.
  2. Find <link rel="alternate" type="application/rss+xml" href=...> in <head>.
  3. Refetch from the discovered URL.
  4. Report the discovered URL in last_status so the user can update their
     source if they want.

If autodiscovery fails (HTML with no feed link), the status should say so
plainly instead of pretending success.
"""
from __future__ import annotations


SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Discovered Feed</title>
    <item>
      <title>First post from the discovered feed</title>
      <link>https://example.com/posts/first</link>
      <description>One.</description>
    </item>
    <item>
      <title>Second post from the discovered feed</title>
      <link>https://example.com/posts/second</link>
      <description>Two.</description>
    </item>
  </channel>
</rss>
"""

HTML_WITH_RSS_DISCOVERY = b"""<!doctype html>
<html>
<head>
  <title>Blog landing page</title>
  <link rel="alternate" type="application/rss+xml" title="RSS"
        href="https://example.com/feed.xml" />
</head>
<body>Not a feed.</body>
</html>
"""

HTML_WITH_ATOM_DISCOVERY = b"""<!doctype html>
<html>
<head>
  <link rel="alternate" type="application/atom+xml"
        href="/atom/feed.xml" />
</head>
<body>HTML page with a relative atom link.</body>
</html>
"""

HTML_WITH_BOTH = b"""<!doctype html>
<html>
<head>
  <link rel="alternate" type="application/rss+xml" href="/feed.rss" />
  <link rel="alternate" type="application/atom+xml" href="/feed.atom" />
</head>
<body></body>
</html>
"""

HTML_WITHOUT_FEED = b"""<!doctype html>
<html>
<head><title>Just a page</title></head>
<body>Nothing here.</body>
</html>
"""


def _patch_http(app_module, monkeypatch, fixtures):
    """fixtures is {url: bytes_or_exception}."""
    def fake(url, *, timeout, max_bytes):
        v = fixtures.get(url)
        if isinstance(v, Exception):
            raise v
        if v is None:
            raise ValueError(f"no fixture for url {url}")
        return v
    monkeypatch.setattr(app_module, "_http_get_bounded", fake)


def _add_test_source(app_module, url, name="Test"):
    with app_module.db_cursor() as conn:
        conn.execute("UPDATE topic_sources SET enabled=0")
        conn.execute(
            "INSERT INTO topic_sources(name, url, enabled) "
            "VALUES (?, ?, 1)",
            (name, url),
        )


# ---------------------------------------------------------------------------
# Sniffer + parser unit tests (no Flask)
# ---------------------------------------------------------------------------

def test_looks_like_html_true_for_html(app_module):
    assert app_module._looks_like_html(b"<!doctype html><html>")
    assert app_module._looks_like_html(b"  \n<html lang='en'>")
    assert app_module._looks_like_html(b"<!DOCTYPE HTML PUBLIC ...")


def test_looks_like_html_false_for_xml_and_text(app_module):
    assert not app_module._looks_like_html(b"<?xml version='1.0'?><rss>")
    assert not app_module._looks_like_html(b"<rss version='2.0'>")
    assert not app_module._looks_like_html(b"plain text")


def test_discover_feed_url_finds_rss_link(app_module):
    discovered = app_module._discover_feed_url(
        HTML_WITH_RSS_DISCOVERY, "https://example.com/blog"
    )
    assert discovered == "https://example.com/feed.xml"


def test_discover_feed_url_resolves_relative_href(app_module):
    discovered = app_module._discover_feed_url(
        HTML_WITH_ATOM_DISCOVERY, "https://example.com/blog/page"
    )
    assert discovered == "https://example.com/atom/feed.xml"


def test_discover_feed_url_prefers_atom_when_both_present(app_module):
    discovered = app_module._discover_feed_url(
        HTML_WITH_BOTH, "https://example.com/"
    )
    assert discovered == "https://example.com/feed.atom"


def test_discover_feed_url_returns_none_when_no_link(app_module):
    assert app_module._discover_feed_url(
        HTML_WITHOUT_FEED, "https://example.com/"
    ) is None


# ---------------------------------------------------------------------------
# Integration: HTML page → discovered feed → entries
# ---------------------------------------------------------------------------

def test_fetch_autodiscovers_from_html_page(client, app_module, monkeypatch):
    _add_test_source(app_module, "https://example.com/blog")
    _patch_http(app_module, monkeypatch, {
        "https://example.com/blog": HTML_WITH_RSS_DISCOVERY,
        "https://example.com/feed.xml": SAMPLE_RSS,
    })

    r = client.post("/api/topics/fetch", json={})
    body = r.get_json()
    assert body["ok"] is True
    assert body["inserted_total"] == 2

    per = body["per_source"][0]
    assert per["discovered_url"] == "https://example.com/feed.xml"
    assert per["error"] is None

    # The source's last_status should mention the discovered URL
    sources = client.get("/api/topics/sources").get_json()
    test_src = next(s for s in sources if s["name"] == "Test")
    assert "via https://example.com/feed.xml" in test_src["last_status"]


def test_fetch_html_without_feed_link_reports_clearly(client, app_module, monkeypatch):
    _add_test_source(app_module, "https://example.com/no-feed")
    _patch_http(app_module, monkeypatch, {
        "https://example.com/no-feed": HTML_WITHOUT_FEED,
    })

    r = client.post("/api/topics/fetch", json={})
    body = r.get_json()
    assert body["ok"] is True
    assert body["inserted_total"] == 0
    per = body["per_source"][0]
    assert per["discovered_url"] is None

    sources = client.get("/api/topics/sources").get_json()
    test_src = next(s for s in sources if s["name"] == "Test")
    # Must NOT say "ok: 0 new" — that's the misleading message we replaced.
    assert "no RSS/Atom link" in test_src["last_status"]


def test_fetch_xml_feed_no_autodiscovery_round_trip(client, app_module, monkeypatch):
    """When the source IS a feed (XML, not HTML), no autodiscovery happens.
    Verify by counting calls to _http_get_bounded."""
    _add_test_source(app_module, "https://example.com/direct-feed.xml")

    call_count = {"n": 0}
    fixtures = {"https://example.com/direct-feed.xml": SAMPLE_RSS}

    def fake(url, *, timeout, max_bytes):
        call_count["n"] += 1
        return fixtures[url]

    monkeypatch.setattr(app_module, "_http_get_bounded", fake)

    r = client.post("/api/topics/fetch", json={})
    assert r.get_json()["inserted_total"] == 2
    # Exactly one HTTP call — no autodiscovery refetch
    assert call_count["n"] == 1

    sources = client.get("/api/topics/sources").get_json()
    test_src = next(s for s in sources if s["name"] == "Test")
    assert "via" not in test_src["last_status"]


# ---------------------------------------------------------------------------
# Default seeds are the fixed ones
# ---------------------------------------------------------------------------

def test_default_seeds_use_working_urls(app_module):
    """The broken seeds (dev.to/feed/top/week, anthropic rss.xml) are gone."""
    with app_module.db_cursor() as conn:
        urls = {r["url"] for r in conn.execute(
            "SELECT url FROM topic_sources"
        ).fetchall()}
    assert "https://dev.to/feed/top/week" not in urls
    assert "https://www.anthropic.com/news/rss.xml" not in urls
    assert "https://hnrss.org/frontpage" in urls
    assert "https://dev.to/feed" in urls
