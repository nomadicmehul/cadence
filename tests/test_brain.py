"""Tests for the weekly brain reflection loop.

The reflection endpoint calls Claude, so we monkeypatch `call_claude` at the
module level to return a canned JSON payload. The rest of the path — context
gathering, ideas insertion, signals serialization — runs for real.
"""
from __future__ import annotations

import json


CANNED_REFLECTION = {
    "summary": "Story posts about migration carried the week. Tutorials are flat. Try a contrarian post on cloud bills.",
    "signals": {
        "best_pillar": "Personal stories",
        "best_format": "story",
        "weakest_pillar": "Tactical tutorials",
        "topics_to_double_down_on": ["cloud bills", "team scaling", "build vs buy"],
    },
    "next_ideas": [
        {"title": "Why we killed our staging cluster",
         "hook": "We deleted staging last Friday.",
         "angle": "Cost was 40% of prod. Nobody used it.",
         "format": "contrarian", "pillar": "Personal stories"},
        {"title": "The one tool I'd put on every laptop",
         "hook": "If I joined a new team tomorrow.",
         "angle": "First install, no exceptions.",
         "format": "list", "pillar": "Tools and workflows"},
        {"title": "What conference travel taught me",
         "hook": "Six talks in eight weeks.",
         "angle": "Lessons that surprised me.",
         "format": "story", "pillar": "Behind the scenes"},
    ],
}


def _patch_claude(app_module, monkeypatch, payload=None):
    """Force `call_claude` to return the canned JSON, sidestepping real AI."""
    text = json.dumps(payload if payload is not None else CANNED_REFLECTION)

    def fake(system, user, model=None, max_tokens=None, json_mode=False):
        return text

    monkeypatch.setattr(app_module, "call_claude", fake)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_reflections_table_exists_and_v2_recorded(app_module):
    with app_module.db_cursor() as conn:
        versions = {r["version"] for r in conn.execute(
            "SELECT version FROM schema_version"
        ).fetchall()}
        # The table must exist (PRAGMA returns rows for known tables)
        cols = conn.execute("PRAGMA table_info(reflections)").fetchall()
    assert 2 in versions
    col_names = {c["name"] for c in cols}
    assert {"summary", "signals_json", "ideas_created_json",
            "window_days", "created_at"}.issubset(col_names)


def test_reflections_round_trip_through_backup(client, app_module, monkeypatch):
    _patch_claude(app_module, monkeypatch)
    r = client.post("/api/brain/reflect", json={"window_days": 7})
    assert r.status_code == 200 and r.get_json()["ok"]

    backup = client.get("/api/backup/export").get_json()
    assert "reflections" in backup["tables"]
    assert len(backup["tables"]["reflections"]) == 1
    assert "Story posts" in backup["tables"]["reflections"][0]["summary"]


# ---------------------------------------------------------------------------
# Reflect endpoint
# ---------------------------------------------------------------------------

def test_reflect_creates_reflection_and_three_ideas(client, app_module, monkeypatch):
    _patch_claude(app_module, monkeypatch)
    r = client.post("/api/brain/reflect", json={"window_days": 7})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert "Story posts" in body["summary"]
    assert body["signals"]["best_format"] == "story"
    assert len(body["ideas_created"]) == 3

    # Ideas show up tagged as auto-reflection
    ideas = client.get("/api/ideas").get_json()
    sources = {i["source"] for i in ideas}
    assert "auto-reflection" in sources
    titles = {i["title"] for i in ideas}
    assert "Why we killed our staging cluster" in titles


def test_reflect_clamps_window_days(client, app_module, monkeypatch):
    captured = {}

    def fake(system, user, model=None, max_tokens=None, json_mode=False):
        captured["user"] = user
        return json.dumps(CANNED_REFLECTION)

    monkeypatch.setattr(app_module, "call_claude", fake)
    r = client.post("/api/brain/reflect", json={"window_days": 9999})
    assert r.status_code == 200
    # Clamp is 90
    assert "last 90 days" in captured["user"]


def test_reflect_assigns_pillar_when_name_matches(client, app_module, monkeypatch):
    _patch_claude(app_module, monkeypatch)
    client.post("/api/brain/reflect", json={"window_days": 7})

    with app_module.db_cursor() as conn:
        rows = conn.execute(
            "SELECT i.title, p.name as pillar FROM ideas i "
            "LEFT JOIN pillars p ON p.id = i.pillar_id "
            "WHERE i.source='auto-reflection' ORDER BY i.id"
        ).fetchall()
    by_title = {r["title"]: r["pillar"] for r in rows}
    assert by_title["Why we killed our staging cluster"] == "Personal stories"
    assert by_title["The one tool I'd put on every laptop"] == "Tools and workflows"


def test_reflections_list_returns_newest_first(client, app_module, monkeypatch):
    _patch_claude(app_module, monkeypatch)
    client.post("/api/brain/reflect", json={"window_days": 7})
    client.post("/api/brain/reflect", json={"window_days": 14})

    rows = client.get("/api/brain/reflections?limit=10").get_json()
    assert len(rows) == 2
    # Most recent first
    assert rows[0]["window_days"] in (7, 14)
    assert isinstance(rows[0]["signals"], dict)
    assert isinstance(rows[0]["ideas_created"], list)


def test_reflect_propagates_ai_error_as_500(client, app_module, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("simulated AI failure")
    monkeypatch.setattr(app_module, "call_claude", boom)
    r = client.post("/api/brain/reflect", json={"window_days": 7})
    assert r.status_code == 500
    assert r.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# Discarded block upgrade
# ---------------------------------------------------------------------------

def test_discarded_block_includes_hook_and_semantic_warning(client, app_module):
    client.post("/api/ideas", json={
        "title": "Killing Kubernetes", "hook": "We retired our cluster.",
        "status": "discarded",
    })
    block = app_module.discarded_block()
    assert "Killing Kubernetes" in block
    assert "We retired our cluster." in block
    assert "SEMANTICALLY SIMILAR" in block


def test_discarded_block_empty_when_no_discards(app_module):
    assert app_module.discarded_block() == ""
