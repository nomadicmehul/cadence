"""Tests for the model picker (Settings -> AI backend -> Model).

Two things to nail down:
1. `get_model()` resolves with the right priority: DB > env > built-in default.
2. The UI-saved model actually reaches the Anthropic SDK call.
3. The Settings PUT validates model strings (no silent garbage).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# is_valid_model — the cheap sanity gate
# ---------------------------------------------------------------------------

def test_is_valid_model_accepts_known_shapes(app_module):
    assert app_module.is_valid_model("claude-sonnet-4-5")
    assert app_module.is_valid_model("claude-opus-4-5")
    assert app_module.is_valid_model("claude-sonnet-4-5-20250929")
    assert app_module.is_valid_model("claude-haiku-4-5")


def test_is_valid_model_rejects_garbage(app_module):
    bad = [
        "", None, "  ", "gpt-4", "sonnet-4-5",  # missing claude- prefix
        "claude-...", "claude- ", "claude-x",   # placeholder/too short
        "claude-" + "x" * 100,                  # too long
        "claude foo",                            # whitespace
    ]
    for v in bad:
        assert not app_module.is_valid_model(v), f"should reject {v!r}"


# ---------------------------------------------------------------------------
# get_model priority order: DB > env > built-in
# ---------------------------------------------------------------------------

def test_get_model_falls_back_to_builtin_default(client, app_module, monkeypatch):
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    app_module.set_setting("claude_model", "")
    assert app_module.get_model() == app_module.BUILTIN_DEFAULT_MODEL


def test_get_model_uses_env_when_db_empty(client, app_module, monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-haiku-4-5")
    app_module.set_setting("claude_model", "")
    assert app_module.get_model() == "claude-haiku-4-5"


def test_get_model_db_beats_env(client, app_module, monkeypatch):
    """DB setting wins because UI is the supported, sticky path."""
    monkeypatch.setenv("CLAUDE_MODEL", "claude-haiku-4-5")
    app_module.set_setting("claude_model", "claude-opus-4-5")
    assert app_module.get_model() == "claude-opus-4-5"


def test_get_model_ignores_invalid_db_value(client, app_module, monkeypatch):
    """Garbage in the DB shouldn't poison the call. Fall through to env/default."""
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-4-5")
    app_module.set_setting("claude_model", "gpt-4")  # invalid prefix
    assert app_module.get_model() == "claude-sonnet-4-5"


def test_get_model_ignores_invalid_env_value(client, app_module, monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "not a model")
    app_module.set_setting("claude_model", "")
    assert app_module.get_model() == app_module.BUILTIN_DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Settings PUT validates model
# ---------------------------------------------------------------------------

def test_settings_put_saves_valid_model(client, app_module):
    r = client.put("/api/settings", json={"claude_model": "claude-opus-4-5"})
    assert r.status_code == 200
    assert app_module.get_setting("claude_model") == "claude-opus-4-5"


def test_settings_put_rejects_invalid_model(client, app_module):
    app_module.set_setting("claude_model", "claude-sonnet-4-5")
    r = client.put("/api/settings", json={"claude_model": "gpt-4"})
    assert r.status_code == 400
    err = r.get_json()["error"]
    assert "claude-" in err  # message tells the user what to expect
    # And the old value is preserved
    assert app_module.get_setting("claude_model") == "claude-sonnet-4-5"


def test_settings_put_allows_empty_to_clear_model(client, app_module):
    """Empty string means 'fall back to env / built-in default'."""
    app_module.set_setting("claude_model", "claude-opus-4-5")
    r = client.put("/api/settings", json={"claude_model": ""})
    assert r.status_code == 200
    assert app_module.get_setting("claude_model") == ""


# ---------------------------------------------------------------------------
# /api/auth/status surfaces the model state for the UI
# ---------------------------------------------------------------------------

def test_auth_status_exposes_active_model_when_api_backend(client, app_module, monkeypatch):
    # Pretend a valid API key is in place
    monkeypatch.setenv("ANTHROPIC_API_KEY",
                       "sk-ant-fake-but-long-enough-to-pass-validation-12345")
    app_module.set_setting("claude_model", "claude-opus-4-5")

    s = client.get("/api/auth/status").get_json()
    assert s["provider"] == "api"
    assert s["active_model"] == "claude-opus-4-5"
    assert s["model_setting"] == "claude-opus-4-5"
    # known_models is a list of dicts the UI builds the dropdown from
    assert isinstance(s["known_models"], list) and len(s["known_models"]) >= 3
    assert all({"id", "label", "blurb"}.issubset(m.keys()) for m in s["known_models"])


def test_auth_status_active_model_blank_on_cli_backend(client, app_module, monkeypatch):
    """The CLI uses Claude Code's configured model, not our setting."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app_module.set_setting("anthropic_api_key", "")
    monkeypatch.setattr(app_module.shutil, "which",
                        lambda name: "/usr/local/bin/claude" if name == "claude" else None)
    # Mock the CLI version probe so it appears authed
    class FakeRun:
        returncode = 0
        stdout = "1.2.3"
        stderr = ""
    monkeypatch.setattr(app_module.subprocess, "run", lambda *a, **kw: FakeRun())

    app_module.set_setting("claude_model", "claude-opus-4-5")
    s = client.get("/api/auth/status").get_json()
    assert s["provider"] == "cli"
    # active_model is empty because the setting can't influence the CLI
    assert s["active_model"] == ""


# ---------------------------------------------------------------------------
# The saved model reaches the Anthropic call site
# ---------------------------------------------------------------------------

def test_call_via_api_uses_db_saved_model(client, app_module, monkeypatch):
    """_call_via_api builds the messages.create kwargs from get_model()."""
    monkeypatch.setenv("ANTHROPIC_API_KEY",
                       "sk-ant-fake-but-long-enough-to-pass-validation-12345")
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    app_module.set_setting("claude_model", "claude-haiku-4-5")

    captured = {}

    class FakeMsg:
        def __init__(self):
            self.content = [type("B", (), {"type": "text", "text": "OK"})()]

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeMsg()

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(app_module, "Anthropic", FakeAnthropic)
    out = app_module._call_via_api("sys", "user", None, None)
    assert out == "OK"
    assert captured["model"] == "claude-haiku-4-5"


def test_call_via_api_respects_per_call_override(client, app_module, monkeypatch):
    """A model passed explicitly to call_claude beats the DB setting."""
    monkeypatch.setenv("ANTHROPIC_API_KEY",
                       "sk-ant-fake-but-long-enough-to-pass-validation-12345")
    app_module.set_setting("claude_model", "claude-haiku-4-5")

    captured = {}

    class FakeMsg:
        def __init__(self):
            self.content = [type("B", (), {"type": "text", "text": "OK"})()]

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeMsg()

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(app_module, "Anthropic", FakeAnthropic)
    app_module._call_via_api("sys", "user", "claude-opus-4-5", None)
    assert captured["model"] == "claude-opus-4-5"


# ---------------------------------------------------------------------------
# Backup carries the model setting through to the new machine
# ---------------------------------------------------------------------------

def test_model_setting_roundtrips_through_backup(client, app_module):
    app_module.set_setting("claude_model", "claude-opus-4-5")
    backup = client.get("/api/backup/export").get_json()
    settings = {r["key"]: r["value"] for r in backup["tables"]["settings"]}
    assert settings["claude_model"] == "claude-opus-4-5"
