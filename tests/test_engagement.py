"""Tests for the comment generator (/api/engagement/comments).

Covers the two things that mattered before this fix:
1. URL-only input is rejected client-side AND server-side with a clear error
   so the spinner doesn't hang against an un-fetchable LinkedIn URL.
2. The creator's voice samples are actually injected into the prompt — the
   pre-fix code path silently bypassed voice_block, violating CLAUDE.md's
   "Don't bypass voice_block" rule.
"""
from __future__ import annotations

import json


CANNED_COMMENTS = {"comments": [
    "Comment one body.",
    "Comment two body.",
    "Comment three body.",
]}


def _capture_call(monkeypatch, app_module, payload=None):
    """Replace call_claude with a recorder that returns canned JSON."""
    seen = {}
    text = json.dumps(payload if payload is not None else CANNED_COMMENTS)

    def fake(system, user, model=None, max_tokens=None, json_mode=False):
        seen["system"] = system
        seen["user"] = user
        return text

    monkeypatch.setattr(app_module, "call_claude", fake)
    return seen


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_empty_target_post_returns_400(client):
    r = client.post("/api/engagement/comments", json={"target_post": "   "})
    assert r.status_code == 400
    assert "body text" in r.get_json()["error"].lower()


def test_url_only_target_post_returns_400(client):
    payloads = [
        "https://www.linkedin.com/posts/foo-bar-12345",
        "http://example.com/post",
        "   https://www.linkedin.com/feed/update/urn:li:activity:7460713439745777665   ",
    ]
    for body in payloads:
        r = client.post("/api/engagement/comments",
                        json={"target_post": body})
        assert r.status_code == 400, f"expected 400 for {body!r}"
        err = r.get_json()["error"]
        assert "URL" in err or "url" in err
        assert "Copy text" in err or "copy" in err.lower()


def test_post_text_with_url_inside_is_allowed(client, app_module, monkeypatch):
    """A real post body might mention a URL. Only pure-URL input is rejected."""
    seen = _capture_call(monkeypatch, app_module)
    body = ("We migrated off Kubernetes last quarter.\n"
            "Write-up here: https://example.com/blog/migration")
    r = client.post("/api/engagement/comments", json={"target_post": body})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert "migrated off Kubernetes" in seen["user"]


# ---------------------------------------------------------------------------
# Voice injection — the real fix
# ---------------------------------------------------------------------------

def test_voice_samples_are_injected_into_system_prompt(client, app_module, monkeypatch):
    # Seed two voice samples; voice_block samples up to 3 random.
    with app_module.db_cursor() as conn:
        conn.execute(
            "INSERT INTO voice_samples(content, label) VALUES (?, ?)",
            ("My signature opening line about chaos engineering.", "seed"),
        )
        conn.execute(
            "INSERT INTO voice_samples(content, label) VALUES (?, ?)",
            ("Another distinctive phrase: zero-bullshit operator energy.", "seed"),
        )

    seen = _capture_call(monkeypatch, app_module)
    r = client.post("/api/engagement/comments",
                    json={"target_post": "Real post body text goes here."})
    assert r.status_code == 200

    # call_claude received system as a structured list (cached prompt)
    assert isinstance(seen["system"], list)
    static = seen["system"][0]
    assert static.get("cache_control") == {"type": "ephemeral"}
    text = static["text"]
    # Either sample's distinctive phrase should land in the system prompt
    assert ("chaos engineering" in text
            or "zero-bullshit operator energy" in text), (
        "voice samples were not injected into the system prompt"
    )
    # VOICE SAMPLES heading present
    assert "VOICE SAMPLES" in text


def test_voice_block_absent_when_no_samples_does_not_error(client, app_module, monkeypatch):
    """Fresh DB has zero voice samples. Endpoint should still succeed; the
    voice_block helper returns empty string in that case."""
    seen = _capture_call(monkeypatch, app_module)
    r = client.post("/api/engagement/comments",
                    json={"target_post": "Plain post body."})
    assert r.status_code == 200
    static = seen["system"][0]
    assert "VOICE SAMPLES" not in static["text"]


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------

def test_successful_response_returns_three_comments(client, app_module, monkeypatch):
    _capture_call(monkeypatch, app_module)
    r = client.post("/api/engagement/comments",
                    json={"target_post": "Some real post body."})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["comments"] == [
        "Comment one body.",
        "Comment two body.",
        "Comment three body.",
    ]


def test_ai_failure_propagates_as_500(client, app_module, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("simulated AI failure")
    monkeypatch.setattr(app_module, "call_claude", boom)
    r = client.post("/api/engagement/comments",
                    json={"target_post": "Real body."})
    assert r.status_code == 500
    assert "simulated AI failure" in r.get_json()["error"]
