"""Smoke tests — every endpoint should respond, schema should round-trip.

These tests deliberately do NOT exercise the AI path. Anything that calls
out to Claude is mocked at the helper level. The point is to catch import
errors, schema regressions, and broken JSON contracts.
"""
from __future__ import annotations

import json


# ---------------------------------------------------------------------------
# Boot + first-run state
# ---------------------------------------------------------------------------

def test_app_imports_and_db_initializes(app_module):
    """init_db ran without error and applied the baseline migration."""
    with app_module.db_cursor() as conn:
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
    assert {r["version"] for r in rows} == {app_module.CURRENT_SCHEMA_VERSION}


def test_first_run_state_is_clean(client):
    """A fresh DB reports first_run=true with generic pillars and no voice."""
    ob = client.get("/api/onboarding/status").get_json()
    assert ob == {"first_run": True, "has_pillars": True, "has_voice_samples": False}

    settings = client.get("/api/settings").get_json()
    assert settings["creator_name"] == ""
    assert settings["creator_bio"] == ""
    assert settings["target_audience"] == ""
    assert settings["anthropic_api_key_set"] is False
    assert "anthropic_api_key" not in settings  # raw key never shipped to frontend

    pillars = client.get("/api/pillars").get_json()
    assert len(pillars) == 5
    # No personal references in the seed data
    blob = json.dumps(pillars).lower()
    for forbidden in ("mehul", "nomadicmehul", "buildingminds", "auth0", "cloudcaptain"):
        assert forbidden not in blob, f"seed pillar leaked personal data: {forbidden}"

    voice = client.get("/api/voice").get_json()
    assert voice == []


def test_dashboard_endpoint_responds(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.get_json()
    assert "counts" in body and "pillar_mix" in body and "totals" in body


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

def test_onboarding_flips_first_run_and_seeds_voice(client):
    payload = {
        "creator_name": "Test User",
        "creator_handle": "testuser",
        "creator_bio": "I write about things.",
        "target_audience": "People who read things.",
        "voice_samples": [
            {"content": "Sample one body.", "label": "seed"},
            {"content": "Sample two body.", "label": "seed"},
        ],
    }
    r = client.post("/api/onboarding/complete", json=payload)
    assert r.status_code == 200 and r.get_json()["ok"] is True

    ob = client.get("/api/onboarding/status").get_json()
    assert ob["first_run"] is False
    assert ob["has_voice_samples"] is True

    voice = client.get("/api/voice").get_json()
    contents = {v["content"] for v in voice}
    assert contents == {"Sample one body.", "Sample two body."}


def test_onboarding_skips_empty_voice_samples(client):
    r = client.post("/api/onboarding/complete", json={
        "creator_name": "Test",
        "voice_samples": [{"content": "  ", "label": "seed"}, {"content": "real one"}],
    })
    assert r.status_code == 200
    voice = client.get("/api/voice").get_json()
    assert [v["content"] for v in voice] == ["real one"]


# ---------------------------------------------------------------------------
# Backup / restore round-trip
# ---------------------------------------------------------------------------

def test_backup_export_includes_all_tables_and_redacts_key(client, app_module):
    # Save an API key so we can verify it gets redacted
    app_module.set_setting("anthropic_api_key", "sk-ant-fake-but-long-enough-to-pass-validation-12345")

    r = client.get("/api/backup/export")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    payload = json.loads(r.data)
    assert payload["schema_version"] == app_module.CURRENT_SCHEMA_VERSION
    assert set(payload["tables"]) == set(app_module.EXPORT_TABLES)

    # API key should be redacted by default
    settings_rows = {r["key"]: r["value"] for r in payload["tables"]["settings"]}
    assert settings_rows["anthropic_api_key"] == ""


def test_backup_export_can_include_api_key_when_asked(client, app_module):
    real_key = "sk-ant-fake-but-long-enough-to-pass-validation-12345"
    app_module.set_setting("anthropic_api_key", real_key)
    r = client.get("/api/backup/export?redact=0")
    payload = json.loads(r.data)
    settings_rows = {r["key"]: r["value"] for r in payload["tables"]["settings"]}
    assert settings_rows["anthropic_api_key"] == real_key


def test_backup_roundtrip_replaces_data(client, app_module):
    # Add a pillar so we have something distinctive
    client.post("/api/pillars", json={"name": "Custom test pillar", "target_pct": 99})
    r = client.get("/api/backup/export")
    backup = json.loads(r.data)

    # Wipe and reseed to a different state
    client.put("/api/pillars/1", json={"name": "Renamed", "target_pct": 1})

    # Restore from backup
    r2 = client.post("/api/backup/import", json={"payload": backup, "mode": "replace"})
    assert r2.status_code == 200
    result = r2.get_json()
    assert result["ok"] is True
    assert result["imported"]["pillars"] >= 6  # 5 defaults + custom

    # Verify the restored state has our custom pillar
    pillars = client.get("/api/pillars").get_json()
    names = [p["name"] for p in pillars]
    assert "Custom test pillar" in names
    assert "Renamed" not in names


def test_backup_import_rejects_newer_schema(client):
    payload = {"schema_version": 9999, "tables": {}}
    r = client.post("/api/backup/import", json={"payload": payload, "mode": "replace"})
    assert r.status_code == 400
    assert "newer schema" in r.get_json()["error"]


def test_backup_import_validates_payload_shape(client):
    r = client.post("/api/backup/import", json={"payload": "not a dict"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Auth status
# ---------------------------------------------------------------------------

def test_auth_status_with_no_backend_returns_provider_none(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module.shutil, "which", lambda _: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app_module.set_setting("anthropic_api_key", "")
    s = client.get("/api/auth/status").get_json()
    assert s["provider"] == "none"
    assert s["api_key_set"] is False
    assert s["cli_installed"] is False


def test_invalid_api_key_placeholder_is_rejected(app_module):
    # The bug we already fixed: placeholder strings must not count as valid
    assert app_module.is_valid_api_key("sk-ant-...") is False
    assert app_module.is_valid_api_key("sk-ant-paste-your-key-here") is False
    assert app_module.is_valid_api_key("") is False
    assert app_module.is_valid_api_key(None) is False
    # A long-enough sk-ant- prefix without obvious placeholder markers passes
    assert app_module.is_valid_api_key("sk-ant-api03-" + "x" * 40) is True
