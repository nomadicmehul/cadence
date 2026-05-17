"""Tests for the topic intake (RSS) loop.

Real network is never hit. `_http_get_bounded` is monkeypatched to return
canned RSS payloads so we exercise the fetch → parse → dedup → insert path
deterministically.
"""
from __future__ import annotations

import json


SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com/</link>
    <item>
      <title>Why we killed our staging cluster</title>
      <link>https://example.com/posts/staging-cluster</link>
      <description>40% of prod, nobody used it.</description>
      <pubDate>Wed, 14 May 2026 12:00:00 GMT</pubDate>
      <guid>https://example.com/posts/staging-cluster</guid>
    </item>
    <item>
      <title>What conference travel taught me</title>
      <link>https://example.com/posts/conference-travel</link>
      <description>Six talks in eight weeks.</description>
      <pubDate>Tue, 13 May 2026 09:30:00 GMT</pubDate>
      <guid>https://example.com/posts/conference-travel</guid>
    </item>
  </channel>
</rss>
"""

SAMPLE_RSS_OVERLAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Why we killed our staging cluster</title>
      <link>https://example.com/posts/staging-cluster</link>
      <description>Same URL, should be skipped.</description>
    </item>
    <item>
      <title>A brand-new post</title>
      <link>https://example.com/posts/brand-new</link>
      <description>This one is new.</description>
    </item>
  </channel>
</rss>
"""


def _patch_http(app_module, monkeypatch, payload_for_url):
    """Monkeypatch the bounded HTTP getter.

    payload_for_url is either a dict {url: bytes_or_exception} or a callable.
    """
    def fake(url, *, timeout, max_bytes):
        v = (payload_for_url(url) if callable(payload_for_url)
             else payload_for_url.get(url))
        if isinstance(v, Exception):
            raise v
        if v is None:
            raise ValueError(f"no fixture for url {url}")
        return v
    monkeypatch.setattr(app_module, "_http_get_bounded", fake)


# ---------------------------------------------------------------------------
# Schema + seeds
# ---------------------------------------------------------------------------

def test_v3_tables_exist_and_seeded(app_module):
    with app_module.db_cursor() as conn:
        versions = {r["version"] for r in conn.execute(
            "SELECT version FROM schema_version"
        ).fetchall()}
        topic_cols = {c["name"] for c in conn.execute(
            "PRAGMA table_info(topics)"
        ).fetchall()}
        source_cols = {c["name"] for c in conn.execute(
            "PRAGMA table_info(topic_sources)"
        ).fetchall()}
        sources = conn.execute(
            "SELECT name, url, kind, enabled FROM topic_sources"
        ).fetchall()
    assert 3 in versions
    assert {"url", "title", "status", "source_id", "external_id"}.issubset(topic_cols)
    assert {"name", "url", "kind", "enabled"}.issubset(source_cols)
    # Generic seeds present and all enabled. We don't pin the count tightly
    # so adding/removing a default doesn't churn unrelated tests.
    assert len(sources) >= 1
    assert all(r["enabled"] == 1 for r in sources)


# ---------------------------------------------------------------------------
# Sources CRUD
# ---------------------------------------------------------------------------

def test_create_update_delete_source(client):
    r = client.post("/api/topics/sources", json={
        "name": "Custom feed", "url": "https://example.com/custom.xml",
    })
    assert r.status_code == 200
    sid = r.get_json()["id"]

    r = client.put(f"/api/topics/sources/{sid}", json={"enabled": 0})
    assert r.status_code == 200

    sources = client.get("/api/topics/sources").get_json()
    target = next(s for s in sources if s["id"] == sid)
    assert target["enabled"] == 0

    client.delete(f"/api/topics/sources/{sid}")
    sources = client.get("/api/topics/sources").get_json()
    assert all(s["id"] != sid for s in sources)


def test_source_url_must_be_http(client):
    r = client.post("/api/topics/sources", json={
        "name": "bad", "url": "ftp://example.com/x",
    })
    assert r.status_code == 400


def test_duplicate_source_url_is_409(client):
    client.post("/api/topics/sources", json={
        "name": "first", "url": "https://example.com/a.xml",
    })
    r = client.post("/api/topics/sources", json={
        "name": "second", "url": "https://example.com/a.xml",
    })
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Fetch path
# ---------------------------------------------------------------------------

def test_fetch_inserts_topics_and_records_last_status(client, app_module, monkeypatch):
    # Disable seeded sources, add a single test source
    with app_module.db_cursor() as conn:
        conn.execute("UPDATE topic_sources SET enabled=0")
        conn.execute(
            "INSERT INTO topic_sources(name, url, kind, enabled) "
            "VALUES (?, ?, 'rss', 1)",
            ("Test", "https://example.com/feed.xml"),
        )

    _patch_http(app_module, monkeypatch,
                {"https://example.com/feed.xml": SAMPLE_RSS})

    r = client.post("/api/topics/fetch", json={})
    body = r.get_json()
    assert body["ok"] is True
    assert body["inserted_total"] == 2
    assert body["sources_checked"] == 1

    topics = client.get("/api/topics").get_json()
    assert len(topics) == 2
    urls = {t["url"] for t in topics}
    assert "https://example.com/posts/staging-cluster" in urls
    assert "https://example.com/posts/conference-travel" in urls

    sources = client.get("/api/topics/sources").get_json()
    test_src = next(s for s in sources if s["name"] == "Test")
    assert test_src["last_status"].startswith("ok:")
    assert test_src["last_fetched_at"]


def test_fetch_dedupes_by_url_on_second_call(client, app_module, monkeypatch):
    with app_module.db_cursor() as conn:
        conn.execute("UPDATE topic_sources SET enabled=0")
        conn.execute(
            "INSERT INTO topic_sources(name, url, kind, enabled) "
            "VALUES ('Test', 'https://example.com/feed.xml', 'rss', 1)"
        )

    # First fetch: two items
    _patch_http(app_module, monkeypatch,
                {"https://example.com/feed.xml": SAMPLE_RSS})
    client.post("/api/topics/fetch", json={})

    # Second fetch: overlap (one duplicate, one fresh)
    _patch_http(app_module, monkeypatch,
                {"https://example.com/feed.xml": SAMPLE_RSS_OVERLAP})
    r = client.post("/api/topics/fetch", json={})
    body = r.get_json()
    assert body["inserted_total"] == 1
    per = body["per_source"][0]
    assert per["inserted"] == 1
    assert per["skipped_existing"] == 1

    topics = client.get("/api/topics").get_json()
    assert len(topics) == 3  # 2 original + 1 new


def test_fetch_isolates_per_source_errors(client, app_module, monkeypatch):
    with app_module.db_cursor() as conn:
        conn.execute("UPDATE topic_sources SET enabled=0")
        conn.execute(
            "INSERT INTO topic_sources(name, url, kind, enabled) "
            "VALUES ('OK source', 'https://example.com/ok.xml', 'rss', 1)"
        )
        conn.execute(
            "INSERT INTO topic_sources(name, url, kind, enabled) "
            "VALUES ('Broken source', 'https://broken.example.com/x.xml', 'rss', 1)"
        )

    fixtures = {
        "https://example.com/ok.xml": SAMPLE_RSS,
        "https://broken.example.com/x.xml": RuntimeError("DNS go boom"),
    }
    _patch_http(app_module, monkeypatch, fixtures)

    r = client.post("/api/topics/fetch", json={})
    body = r.get_json()
    assert body["ok"] is True
    assert body["sources_checked"] == 2
    assert body["inserted_total"] == 2  # broken source contributed 0, ok added 2

    statuses = {
        s["source_name"]: s for s in body["per_source"]
    }
    assert statuses["OK source"]["error"] is None
    assert "DNS go boom" in statuses["Broken source"]["error"]

    sources = client.get("/api/topics/sources").get_json()
    broken = next(s for s in sources if s["name"] == "Broken source")
    assert broken["last_status"].startswith("error:")


def test_fetch_respects_explicit_source_ids(client, app_module, monkeypatch):
    with app_module.db_cursor() as conn:
        conn.execute("UPDATE topic_sources SET enabled=1")  # all enabled
        rows = conn.execute(
            "SELECT id, url FROM topic_sources ORDER BY id"
        ).fetchall()
    target = rows[0]
    # Map every seeded URL → empty feed; we only want to verify the source_id filter
    fixtures = {r["url"]: b"<rss><channel></channel></rss>" for r in rows}
    _patch_http(app_module, monkeypatch, fixtures)

    seen_urls: list[str] = []
    original_fake = app_module._http_get_bounded

    def tracking(url, *, timeout, max_bytes):
        seen_urls.append(url)
        return original_fake(url, timeout=timeout, max_bytes=max_bytes)

    monkeypatch.setattr(app_module, "_http_get_bounded", tracking)

    r = client.post("/api/topics/fetch", json={"source_ids": [target["id"]]})
    assert r.status_code == 200
    assert seen_urls == [target["url"]]


# ---------------------------------------------------------------------------
# Topics list + status updates
# ---------------------------------------------------------------------------

def test_topics_list_filters_by_status_and_source(client, app_module, monkeypatch):
    with app_module.db_cursor() as conn:
        conn.execute("UPDATE topic_sources SET enabled=0")
        conn.execute(
            "INSERT INTO topic_sources(name, url, enabled) "
            "VALUES ('Test', 'https://example.com/feed.xml', 1)"
        )
    _patch_http(app_module, monkeypatch,
                {"https://example.com/feed.xml": SAMPLE_RSS})
    client.post("/api/topics/fetch", json={})

    topics = client.get("/api/topics").get_json()
    t_id = topics[0]["id"]
    client.put(f"/api/topics/{t_id}", json={"status": "dismissed"})

    new_topics = client.get("/api/topics?status=new").get_json()
    assert all(t["status"] == "new" for t in new_topics)
    assert t_id not in {t["id"] for t in new_topics}

    dismissed = client.get("/api/topics?status=dismissed").get_json()
    assert {t["id"] for t in dismissed} == {t_id}


# ---------------------------------------------------------------------------
# Topic-to-idea draft
# ---------------------------------------------------------------------------

CANNED_TOPIC_DRAFT = {
    "title": "What killing staging really cost us",
    "hook": "We deleted staging on a Friday.",
    "angle": "The savings were obvious. The cultural fallout was not.",
    "format": "story",
    "pillar": "Personal stories",
}


def test_draft_from_topic_creates_idea_and_marks_topic_used(client, app_module, monkeypatch):
    with app_module.db_cursor() as conn:
        conn.execute("UPDATE topic_sources SET enabled=0")
        conn.execute(
            "INSERT INTO topic_sources(name, url, enabled) "
            "VALUES ('Test', 'https://example.com/feed.xml', 1)"
        )
    _patch_http(app_module, monkeypatch,
                {"https://example.com/feed.xml": SAMPLE_RSS})
    client.post("/api/topics/fetch", json={})

    topics = client.get("/api/topics").get_json()
    target = next(t for t in topics if "staging" in t["title"])

    monkeypatch.setattr(
        app_module, "call_claude",
        lambda *a, **kw: json.dumps(CANNED_TOPIC_DRAFT),
    )
    r = client.post(f"/api/topics/{target['id']}/draft", json={})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["idea_id"]

    # Topic was marked used
    updated = client.get(f"/api/topics?status=used").get_json()
    assert target["id"] in {t["id"] for t in updated}

    # Idea row exists with the right source tag
    ideas = client.get("/api/ideas").get_json()
    new_idea = next(i for i in ideas if i["id"] == body["idea_id"])
    assert new_idea["title"] == "What killing staging really cost us"
    assert new_idea["source"] == "topic-intake"
    assert new_idea["pillar_name"] == "Personal stories"
    # Source URL must be preserved in the angle so the user can trace it back
    assert "example.com" in new_idea["angle"]


def test_draft_returns_404_for_unknown_topic(client, app_module, monkeypatch):
    monkeypatch.setattr(
        app_module, "call_claude",
        lambda *a, **kw: json.dumps(CANNED_TOPIC_DRAFT),
    )
    r = client.post("/api/topics/99999/draft", json={})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Backup round-trip with new tables
# ---------------------------------------------------------------------------

def test_backup_includes_topic_tables(client, app_module, monkeypatch):
    with app_module.db_cursor() as conn:
        conn.execute("UPDATE topic_sources SET enabled=0")
        conn.execute(
            "INSERT INTO topic_sources(name, url, enabled) "
            "VALUES ('Test', 'https://example.com/feed.xml', 1)"
        )
    _patch_http(app_module, monkeypatch,
                {"https://example.com/feed.xml": SAMPLE_RSS})
    client.post("/api/topics/fetch", json={})

    backup = client.get("/api/backup/export").get_json()
    assert "topic_sources" in backup["tables"]
    assert "topics" in backup["tables"]
    assert len(backup["tables"]["topics"]) == 2
