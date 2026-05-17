"""Tests for the profile.md round-trip — settings, pillars, voice samples,
and topic sources serialized as a human-editable markdown file.

The key behaviours we lock down:
  - Round-trip is idempotent: export -> parse -> apply leaves the DB in
    the same state as before export.
  - Re-importing the same file is a no-op (no duplicates, no churn).
  - Import is additive: pillars and sources upsert by name/url, voice
    appends new content, NOTHING gets deleted. This protects foreign-key
    references (drafts.pillar_id, topics.source_id, etc.).
  - Invalid values are rejected with a clear warning, not silently saved.
"""
from __future__ import annotations

import textwrap


# ---------------------------------------------------------------------------
# Serialize -> parse -> apply round-trip
# ---------------------------------------------------------------------------

def _seed_profile(app_module):
    """Populate the DB with a realistic profile."""
    app_module.set_setting("creator_name", "Test User")
    app_module.set_setting("creator_handle", "testuser")
    app_module.set_setting("creator_bio",
                           "Multi-line bio.\n\nSecond paragraph.")
    app_module.set_setting("target_audience",
                           "DevOps engineers and platform builders.")
    app_module.set_setting("weekly_target", "5")
    app_module.set_setting("preferred_hours", "09:00,12:30,17:30")
    app_module.set_setting("default_format", "story")

    with app_module.db_cursor() as conn:
        # Wipe and reseed pillars so we have known content
        conn.execute("DELETE FROM pillars")
        conn.executemany(
            "INSERT INTO pillars(name, description, target_pct, color, "
            "sort_order) VALUES (?, ?, ?, ?, ?)",
            [
                ("Industry insights", "Hot takes from the trenches.",
                 30, "#0ea5e9", 1),
                ("Personal stories", "Lessons learned the hard way.",
                 25, "#10b981", 2),
            ],
        )
        conn.execute(
            "INSERT INTO voice_samples(content, label) VALUES (?, ?)",
            ("The day I deleted staging on a Friday afternoon.\n\n"
             "I knew we'd survive. The team didn't.", "opener"),
        )
        conn.execute(
            "INSERT INTO voice_samples(content, label) VALUES (?, ?)",
            ("Six talks in eight weeks. The pattern surprised me.",
             "story"),
        )
        # Seed topic sources too (the migration adds defaults but those
        # might shift over time; we want deterministic state).
        conn.execute("DELETE FROM topic_sources")
        conn.execute(
            "INSERT INTO topic_sources(name, url, kind, enabled) "
            "VALUES ('Hacker News', 'https://hnrss.org/frontpage', 'rss', 1)"
        )
        conn.execute(
            "INSERT INTO topic_sources(name, url, kind, enabled) "
            "VALUES ('Dev.to', 'https://dev.to/feed', 'rss', 0)"
        )


def test_roundtrip_export_parse_apply_preserves_state(client, app_module):
    _seed_profile(app_module)
    before = app_module._gather_profile_data()

    md = app_module._profile_to_markdown(before)
    parsed = app_module._parse_profile_markdown(md)
    counts = app_module._apply_profile_dict(parsed)

    after = app_module._gather_profile_data()

    # Scalar settings preserved
    for k in ("name", "handle", "bio", "target_audience",
              "weekly_target", "preferred_hours", "default_format"):
        assert before[k] == after[k], f"setting drift on {k!r}"

    # Pillars: same set, same order (upsert kept their identity, sort_order
    # preserved)
    assert [p["name"] for p in after["pillars"]] == \
           [p["name"] for p in before["pillars"]]
    for b, a in zip(before["pillars"], after["pillars"]):
        assert a["description"] == b["description"]
        assert a["target_pct"] == b["target_pct"]
        assert a["color"] == b["color"]
        assert a["sort_order"] == b["sort_order"]

    # Voice samples: re-import doesn't duplicate. Same content set.
    assert {s["content"] for s in after["voice_samples"]} == \
           {s["content"] for s in before["voice_samples"]}
    assert counts["voice_inserted"] == 0
    assert counts["voice_skipped_duplicates"] == len(before["voice_samples"])

    # Topic sources: same as pillars — upsert by URL.
    assert {s["url"] for s in after["topic_sources"]} == \
           {s["url"] for s in before["topic_sources"]}


def test_export_round_trips_through_http_endpoint(client, app_module):
    _seed_profile(app_module)
    r = client.get("/api/profile/export")
    assert r.status_code == 200
    cd = r.headers.get("Content-Disposition", "")
    assert "profile" in cd and cd.endswith(".md\"")
    md = r.data.decode("utf-8")
    assert "name: Test User" in md
    assert "## Bio" in md
    assert "## Pillars" in md
    assert "Industry insights" in md
    assert "## Voice samples" in md
    assert "deleted staging" in md
    assert "## Topic sources" in md
    assert "hnrss.org" in md

    # Re-import the exact same file -> no changes
    r2 = client.post("/api/profile/import", json={"markdown": md})
    assert r2.status_code == 200
    body = r2.get_json()
    assert body["ok"] is True
    assert body["pillars_inserted"] == 0
    assert body["voice_inserted"] == 0
    assert body["sources_inserted"] == 0


# ---------------------------------------------------------------------------
# Import is additive — never deletes existing rows
# ---------------------------------------------------------------------------

def test_import_does_not_delete_pillars_missing_from_file(client, app_module):
    """A pillar the user has in DB but not in the file should be preserved.
    This is critical because drafts.pillar_id references pillars(id)."""
    _seed_profile(app_module)
    # File mentions only ONE pillar
    md = textwrap.dedent("""\
        ---
        name: Test User
        ---

        ## Pillars

        ### Industry insights
        - target_pct: 40
        - color: #0ea5e9
        - sort_order: 1

        Updated description for industry insights.
    """)
    r = client.post("/api/profile/import", json={"markdown": md})
    assert r.status_code == 200
    body = r.get_json()
    assert body["pillars_updated"] == 1
    assert body["pillars_inserted"] == 0

    after = app_module._gather_profile_data()
    names = {p["name"] for p in after["pillars"]}
    # Personal stories was NOT in the file but must still be present
    assert "Personal stories" in names
    assert "Industry insights" in names
    # The targeted update did go through
    insight = next(p for p in after["pillars"] if p["name"] == "Industry insights")
    assert insight["target_pct"] == 40
    assert "Updated description" in insight["description"]


def test_import_preserves_foreign_key_refs_on_drafts(client, app_module):
    """Concretely: drafts pointing at a pillar must keep pointing after
    import. The upsert path updates in place; it doesn't DELETE+INSERT."""
    _seed_profile(app_module)
    with app_module.db_cursor() as conn:
        pillar_id = conn.execute(
            "SELECT id FROM pillars WHERE name='Industry insights'"
        ).fetchone()["id"]
        cur = conn.execute(
            "INSERT INTO drafts(title, body, status, pillar_id) "
            "VALUES ('Linked draft', 'Body.', 'draft', ?)",
            (pillar_id,),
        )
        draft_id = cur.lastrowid

    md = app_module._profile_to_markdown(app_module._gather_profile_data())
    r = client.post("/api/profile/import", json={"markdown": md})
    assert r.status_code == 200

    with app_module.db_cursor() as conn:
        row = conn.execute(
            "SELECT pillar_id FROM drafts WHERE id=?", (draft_id,)
        ).fetchone()
    assert row["pillar_id"] == pillar_id, (
        "draft lost its pillar reference — the import path must UPSERT "
        "by name, not DELETE+INSERT"
    )


def test_import_appends_new_voice_samples_without_dupes(client, app_module):
    """A file with one existing sample + one new sample should insert
    the new one and skip the existing as a duplicate. H3 entries must
    live inside the `## Voice samples` H2 section, not below it."""
    _seed_profile(app_module)

    md = textwrap.dedent("""\
        ## Voice samples

        ### Sample 1
        - label: opener

        The day I deleted staging on a Friday afternoon.

        I knew we'd survive. The team didn't.

        ### Sample 2
        - label: contrarian

        We don't need a 'best practices' document. We need taste.
    """)

    r = client.post("/api/profile/import", json={"markdown": md})
    assert r.status_code == 200
    body = r.get_json()
    assert body["voice_inserted"] == 1
    # One of the existing seeded samples matches "deleted staging" content
    assert body["voice_skipped_duplicates"] >= 1

    after = app_module._gather_profile_data()
    contents = [s["content"] for s in after["voice_samples"]]
    assert any("We don't need a 'best practices'" in c for c in contents)
    # Originals still there (additive semantics; never deletes)
    assert any("deleted staging" in c for c in contents)
    assert any("Six talks" in c for c in contents)


def test_import_does_not_delete_topic_sources_missing_from_file(
    client, app_module,
):
    _seed_profile(app_module)
    md = textwrap.dedent("""\
        ## Topic sources

        ### Hacker News
        - url: https://hnrss.org/frontpage
        - kind: rss
        - enabled: false
    """)
    r = client.post("/api/profile/import", json={"markdown": md})
    assert r.status_code == 200
    body = r.get_json()
    assert body["sources_updated"] == 1

    after = app_module._gather_profile_data()
    urls = {s["url"] for s in after["topic_sources"]}
    # dev.to was in DB but not in the file -> must still be present
    assert "https://dev.to/feed" in urls
    # HN got its enabled flag flipped to 0
    hn = next(s for s in after["topic_sources"]
              if s["url"] == "https://hnrss.org/frontpage")
    assert hn["enabled"] == 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_import_rejects_bad_default_format_with_warning(client, app_module):
    app_module.set_setting("default_format", "story")
    md = textwrap.dedent("""\
        ---
        default_format: not-a-real-format
        ---
    """)
    r = client.post("/api/profile/import", json={"markdown": md})
    body = r.get_json()
    assert body["ok"] is True
    assert app_module.get_setting("default_format") == "story"  # unchanged
    assert any("default_format" in w for w in body["warnings"])


def test_import_rejects_out_of_range_weekly_target(client, app_module):
    app_module.set_setting("weekly_target", "5")
    md = textwrap.dedent("""\
        ---
        weekly_target: 99
        ---
    """)
    r = client.post("/api/profile/import", json={"markdown": md})
    body = r.get_json()
    assert body["ok"] is True
    assert app_module.get_setting("weekly_target") == "5"  # unchanged
    assert any("weekly_target" in w for w in body["warnings"])


def test_import_empty_markdown_returns_400(client):
    r = client.post("/api/profile/import", json={"markdown": ""})
    assert r.status_code == 400


def test_unknown_h2_section_surfaces_warning_but_doesnt_fail(client):
    md = textwrap.dedent("""\
        ## Pillars

        ### A pillar
        - target_pct: 10

        Body.

        ## Something totally made up

        Body that gets ignored.
    """)
    r = client.post("/api/profile/import", json={"markdown": md})
    body = r.get_json()
    assert body["ok"] is True
    assert any("Something totally made up" in w for w in body["warnings"])
    assert body["pillars_inserted"] == 1


# ---------------------------------------------------------------------------
# Empty placeholders shouldn't write back as real content
# ---------------------------------------------------------------------------

def test_empty_placeholder_does_not_overwrite_bio(client, app_module):
    """If the user exported when bio was empty (file shows `_(empty)_`),
    a re-import shouldn't write the literal "_(empty)_" string into bio."""
    app_module.set_setting("creator_bio", "Real bio that exists.")
    md = textwrap.dedent("""\
        ## Bio

        _(empty)_
    """)
    r = client.post("/api/profile/import", json={"markdown": md})
    assert r.status_code == 200
    assert app_module.get_setting("creator_bio") == "Real bio that exists."
