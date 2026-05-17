"""Tests for the full markdown backup (.zip) — the human-editable companion
to the JSON backup.

The behaviours that matter:
  1. The archive contains the expected files (profile.md, ideas.md,
     reflections.md, topics.md, analytics.csv, drafts/*.md, manifest.json).
  2. Round-trip preserves DB state: export, import, no churn.
  3. Per-table UPSERT BY ID for drafts/ideas/reflections/analytics:
     editing one file and re-importing UPDATES that row, doesn't create
     a duplicate.
  4. Schema-version gate refuses archives from a newer schema.
  5. Additive semantics — re-import never deletes rows that aren't in
     the archive.
  6. Drafts with markdown headings IN their body still round-trip safely
     (the parser reads body verbatim after the closing frontmatter `---`).
"""
from __future__ import annotations

import base64
import io
import json
import zipfile


def _seed_full_db(app_module):
    """Populate every table with deterministic content."""
    app_module.set_setting("creator_name", "Test User")
    app_module.set_setting("creator_handle", "testuser")
    app_module.set_setting("creator_bio", "Bio paragraph.")
    app_module.set_setting("target_audience", "Engineers.")
    with app_module.db_cursor() as conn:
        conn.execute("DELETE FROM pillars")
        conn.execute("DELETE FROM voice_samples")
        conn.execute("DELETE FROM topic_sources")
        conn.execute("DELETE FROM ideas")
        conn.execute("DELETE FROM drafts")
        conn.execute("DELETE FROM analytics")
        conn.execute("DELETE FROM reflections")
        conn.execute("DELETE FROM topics")
        conn.executemany(
            "INSERT INTO pillars(name, description, target_pct, color, "
            "sort_order) VALUES (?, ?, ?, ?, ?)",
            [
                ("Industry insights", "Hot takes.", 30, "#0ea5e9", 1),
                ("Personal stories", "Lessons learned.", 25, "#10b981", 2),
            ],
        )
        conn.execute(
            "INSERT INTO voice_samples(content, label) VALUES (?, ?)",
            ("The day I deleted staging.", "opener"),
        )
        conn.execute(
            "INSERT INTO topic_sources(name, url, kind, enabled) "
            "VALUES ('Hacker News', 'https://hnrss.org/frontpage', 'rss', 1)"
        )
        pillar_id = conn.execute(
            "SELECT id FROM pillars WHERE name='Industry insights'"
        ).fetchone()["id"]
        cur = conn.execute(
            "INSERT INTO ideas(pillar_id, title, hook, angle, source, status) "
            "VALUES (?, 'Idea title', 'Stop scrolling.', 'A specific angle.', "
            "'manual', 'raw')",
            (pillar_id,),
        )
        idea_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO drafts(idea_id, pillar_id, title, body, format, "
            "status, hook_score, voice_score, posted_at) "
            "VALUES (?, ?, ?, ?, 'story', 'published', 8, 9, "
            "'2026-05-15T10:00:00')",
            (idea_id, pillar_id, "Killed our staging cluster",
             "We deleted staging on a Friday.\n\nIt went fine."),
        )
        draft_id = cur.lastrowid
        conn.execute(
            "INSERT INTO analytics(draft_id, impressions, likes, comments) "
            "VALUES (?, 4669, 98, 12)",
            (draft_id,),
        )
        conn.execute(
            "INSERT INTO reflections(window_days, summary, signals_json, "
            "ideas_created_json) VALUES (7, 'Story posts carried the week.', "
            "'{\"best_pillar\":\"Industry insights\",\"best_format\":\"story\"}', "
            "'[1, 2, 3]')"
        )
        source_id = conn.execute(
            "SELECT id FROM topic_sources WHERE name='Hacker News'"
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO topics(source_id, url, title, summary, status, "
            "published_at) VALUES (?, 'https://example.com/post1', "
            "'A great post', 'Summary text.', 'new', '2026-05-14T10:00:00')",
            (source_id,),
        )


# ---------------------------------------------------------------------------
# Archive shape
# ---------------------------------------------------------------------------

def test_export_zip_contains_expected_files(client, app_module):
    _seed_full_db(app_module)
    r = client.get("/api/backup/export-markdown")
    assert r.status_code == 200
    assert r.headers.get("Content-Type", "").startswith("application/zip")

    zf = zipfile.ZipFile(io.BytesIO(r.data))
    names = zf.namelist()
    # All files live under a single root folder; pull it
    roots = {n.split("/", 1)[0] for n in names if "/" in n}
    assert len(roots) == 1
    root = next(iter(roots))

    required = [
        f"{root}/manifest.json",
        f"{root}/profile.md",
        f"{root}/ideas.md",
        f"{root}/reflections.md",
        f"{root}/topics.md",
        f"{root}/analytics.csv",
    ]
    for r_ in required:
        assert r_ in names, f"missing {r_} in archive"

    drafts_files = [n for n in names
                    if n.startswith(f"{root}/drafts/") and n.endswith(".md")]
    assert len(drafts_files) == 1
    # Filename pattern NNNN-slug.md
    assert any("killed-our-staging-cluster" in n for n in drafts_files)


def test_manifest_has_schema_version_and_counts(client, app_module):
    _seed_full_db(app_module)
    r = client.get("/api/backup/export-markdown")
    zf = zipfile.ZipFile(io.BytesIO(r.data))
    root = next(iter({n.split("/", 1)[0] for n in zf.namelist() if "/" in n}))
    manifest = json.loads(zf.read(f"{root}/manifest.json").decode("utf-8"))
    assert manifest["schema_version"] == app_module.CURRENT_SCHEMA_VERSION
    assert manifest["counts"]["drafts"] == 1
    assert manifest["counts"]["ideas"] == 1
    assert manifest["counts"]["analytics"] == 1
    assert manifest["counts"]["pillars"] == 2


# ---------------------------------------------------------------------------
# Round-trip is a no-op
# ---------------------------------------------------------------------------

def _post_import(client, zip_bytes: bytes):
    return client.post("/api/backup/import-markdown", json={
        "zip_base64": base64.b64encode(zip_bytes).decode("ascii"),
    })


def test_export_then_import_does_not_churn(client, app_module):
    _seed_full_db(app_module)
    r = client.get("/api/backup/export-markdown")
    assert r.status_code == 200

    before_counts = _row_counts(app_module)

    r2 = _post_import(client, r.data)
    assert r2.status_code == 200
    body = r2.get_json()
    assert body["ok"] is True
    # Nothing inserted because everything exists with the same id
    assert body["drafts_inserted"] == 0
    assert body["ideas_inserted"] == 0
    assert body["reflections_inserted"] == 0
    assert body["analytics_inserted"] == 0
    assert body["pillars_inserted"] == 0
    assert body["voice_inserted"] == 0

    after_counts = _row_counts(app_module)
    assert before_counts == after_counts, (
        "Re-importing the same archive changed row counts somewhere — "
        "the additive UPSERT semantics broke."
    )


def _row_counts(app_module):
    tables = ["pillars", "voice_samples", "topic_sources", "ideas",
              "drafts", "analytics", "reflections", "topics"]
    with app_module.db_cursor() as conn:
        return {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}")
                .fetchone()["n"] for t in tables}


# ---------------------------------------------------------------------------
# UPSERT BY ID — editing a draft file updates the row, doesn't duplicate
# ---------------------------------------------------------------------------

def test_edited_draft_body_updates_existing_row(client, app_module):
    _seed_full_db(app_module)
    r = client.get("/api/backup/export-markdown")
    zf_in = zipfile.ZipFile(io.BytesIO(r.data))
    root = next(iter({n.split("/", 1)[0] for n in zf_in.namelist() if "/" in n}))
    drafts_files = [n for n in zf_in.namelist()
                    if n.startswith(f"{root}/drafts/") and n.endswith(".md")]
    original = zf_in.read(drafts_files[0]).decode("utf-8")

    # Edit the body — replace one sentence
    edited = original.replace(
        "We deleted staging on a Friday.",
        "We deleted staging on a Tuesday afternoon."
    )
    assert edited != original

    # Build a new zip with the edited draft (everything else identical)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf_out:
        for n in zf_in.namelist():
            content = (edited.encode("utf-8") if n == drafts_files[0]
                       else zf_in.read(n))
            zf_out.writestr(n, content)

    before_count = _row_counts(app_module)["drafts"]
    r2 = _post_import(client, out.getvalue())
    body = r2.get_json()
    assert body["drafts_updated"] == 1
    assert body["drafts_inserted"] == 0

    after_count = _row_counts(app_module)["drafts"]
    assert before_count == after_count  # no duplicate row

    drafts = client.get("/api/drafts").get_json()
    edited_draft = next(d for d in drafts
                        if "Tuesday afternoon" in (d["body"] or ""))
    assert "Friday" not in edited_draft["body"]


def test_draft_with_markdown_headings_in_body_roundtrips(client, app_module):
    """Body may legitimately contain ##, ###, etc. The draft parser must
    read body verbatim after the closing frontmatter `---`, not split on
    headings."""
    _seed_full_db(app_module)
    body_with_headings = (
        "Here's the lesson.\n\n"
        "## Step 1\n\n"
        "Stop scrolling.\n\n"
        "### Detail\n\n"
        "It's harder than it sounds.\n"
    )
    with app_module.db_cursor() as conn:
        cur = conn.execute(
            "INSERT INTO drafts(title, body, format, status) "
            "VALUES ('Markdown body test', ?, 'tutorial', 'draft')",
            (body_with_headings,),
        )
        draft_id = cur.lastrowid

    # Export, then re-import. Body should survive intact.
    r = client.get("/api/backup/export-markdown")
    r2 = _post_import(client, r.data)
    assert r2.status_code == 200

    drafts = client.get("/api/drafts").get_json()
    target = next(d for d in drafts if d["id"] == draft_id)
    assert "## Step 1" in target["body"]
    assert "### Detail" in target["body"]


# ---------------------------------------------------------------------------
# Additive semantics — re-import doesn't delete rows that aren't in archive
# ---------------------------------------------------------------------------

def test_reimport_does_not_delete_rows_missing_from_archive(client, app_module):
    _seed_full_db(app_module)
    r = client.get("/api/backup/export-markdown")
    zip_bytes = r.data

    # Add a new draft AFTER the export. It's not in the archive.
    with app_module.db_cursor() as conn:
        conn.execute(
            "INSERT INTO drafts(title, body, status) "
            "VALUES ('Added after export', 'Body.', 'draft')"
        )

    before_drafts = _row_counts(app_module)["drafts"]

    r2 = _post_import(client, zip_bytes)
    assert r2.status_code == 200

    after_drafts = _row_counts(app_module)["drafts"]
    assert after_drafts == before_drafts  # the new draft survived
    drafts = client.get("/api/drafts").get_json()
    assert any(d["title"] == "Added after export" for d in drafts)


# ---------------------------------------------------------------------------
# Schema version gate
# ---------------------------------------------------------------------------

def test_import_rejects_archive_from_newer_schema(client, app_module):
    """Build a tiny zip with a future schema_version. Should 400."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "schema_version": 9999,
            "format_version": 1,
            "counts": {},
        }))
    r = _post_import(client, buf.getvalue())
    assert r.status_code == 400
    assert "newer schema" in r.get_json()["error"]


def test_import_rejects_non_zip_payload(client, app_module):
    r = _post_import(client, b"not a zip")
    assert r.status_code == 400


def test_export_redacts_api_key_via_profile_md(client, app_module):
    """The API key never lands in the archive (it's not in profile.md
    frontmatter, and the manifest doesn't carry it)."""
    app_module.set_setting("anthropic_api_key",
                           "sk-ant-fake-but-long-enough-to-pass-validation-12345")
    r = client.get("/api/backup/export-markdown")
    zip_bytes = r.data
    # Just grep the raw bytes; the key string must not appear anywhere
    assert b"sk-ant-fake" not in zip_bytes


# ---------------------------------------------------------------------------
# Empty DB still produces a valid archive
# ---------------------------------------------------------------------------

def test_export_works_on_fresh_db(client, app_module):
    """No drafts, no ideas, etc. Archive should still be valid and parse."""
    r = client.get("/api/backup/export-markdown")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.data))
    names = zf.namelist()
    # All required files present even when sources are empty
    assert any(n.endswith("/manifest.json") for n in names)
    assert any(n.endswith("/profile.md") for n in names)
    assert any(n.endswith("/ideas.md") for n in names)
    assert any(n.endswith("/analytics.csv") for n in names)
    # Re-import the empty archive into a fresh DB: no errors, no inserts
    r2 = _post_import(client, r.data)
    assert r2.status_code == 200
    body = r2.get_json()
    assert body["drafts_inserted"] == 0
