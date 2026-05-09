"""
Cadence — a content pipeline for LinkedIn

A self-hosted Flask app that turns posting into a repeatable pipeline:
    Ideas  →  Drafts  →  Scheduled  →  Published  →  Analytics  →  Repurpose

All AI generation is powered by Claude (Anthropic). No data leaves your machine
except the prompts you send to the Claude API.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import textwrap
from contextlib import contextmanager
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any

from flask import Flask, g, jsonify, render_template, request

# Anthropic SDK is optional at import time so the app boots without a key.
try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "pipeline.db"

DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "2048"))

app = Flask(__name__, static_folder="static", template_folder="templates")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS pillars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    target_pct INTEGER DEFAULT 20,
    color TEXT DEFAULT '#6366f1',
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pillar_id INTEGER REFERENCES pillars(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    hook TEXT,
    angle TEXT,
    source TEXT,
    status TEXT DEFAULT 'raw',  -- raw | drafted | discarded
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER REFERENCES ideas(id) ON DELETE SET NULL,
    pillar_id INTEGER REFERENCES pillars(id) ON DELETE SET NULL,
    title TEXT,
    body TEXT NOT NULL,
    format TEXT DEFAULT 'story',  -- story | list | contrarian | tutorial | carousel | bts
    hook_score INTEGER,
    voice_score INTEGER,
    score_notes TEXT,
    status TEXT DEFAULT 'draft',  -- draft | ready | scheduled | published
    scheduled_for TEXT,
    posted_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id INTEGER REFERENCES drafts(id) ON DELETE CASCADE,
    impressions INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    reposts INTEGER DEFAULT 0,
    follows INTEGER DEFAULT 0,
    profile_visits INTEGER DEFAULT 0,
    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS voice_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    label TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS engagement_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id INTEGER REFERENCES drafts(id) ON DELETE SET NULL,
    type TEXT DEFAULT 'comment',  -- comment | follow_up | respond
    details TEXT,
    due_date TEXT,
    completed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def db_cursor():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema migrations
#
# Each migration is a (version, function) pair. Functions take a connection,
# run their SQL, and must be idempotent (safe to re-run if interrupted).
# ---------------------------------------------------------------------------

CURRENT_SCHEMA_VERSION = 1


def _migration_v1(conn: sqlite3.Connection) -> None:
    """Baseline. SCHEMA covers all tables; nothing extra to do here."""
    pass


MIGRATIONS: list[tuple[int, Any]] = [
    (1, _migration_v1),
]


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM schema_version").fetchall()
    return {r["version"] for r in rows}


def init_db():
    with db_cursor() as conn:
        conn.executescript(SCHEMA)
        applied = _applied_versions(conn)
        for version, fn in MIGRATIONS:
            if version in applied:
                continue
            fn(conn)
            conn.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                (version, datetime.utcnow().isoformat(timespec="seconds")),
            )
        # Seed default pillars + voice samples + settings on first run only.
        # Each block is gated on its own table being empty so partial-seed
        # databases (e.g. user wiped pillars but kept voice) don't get re-seeded.
        cur = conn.execute("SELECT COUNT(*) AS n FROM pillars")
        if cur.fetchone()["n"] == 0:
            conn.executemany(
                "INSERT INTO pillars(name, description, target_pct, color, sort_order)"
                " VALUES (?, ?, ?, ?, ?)",
                DEFAULT_PILLARS,
            )
        cur = conn.execute("SELECT COUNT(*) AS n FROM voice_samples")
        if cur.fetchone()["n"] == 0 and DEFAULT_VOICE_SAMPLES:
            conn.executemany(
                "INSERT INTO voice_samples(content, label) VALUES (?, ?)",
                DEFAULT_VOICE_SAMPLES,
            )
        cur = conn.execute("SELECT COUNT(*) AS n FROM settings")
        if cur.fetchone()["n"] == 0:
            for k, v in DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?)", (k, v)
                )


# ---------------------------------------------------------------------------
# Seed data — generic starter pillars and empty creator profile
#
# These constants only affect *fresh* installs (init_db inserts only when a
# table is empty). Existing databases are untouched. The first-run onboarding
# flow in the UI lets new users edit these in 30 seconds.
# ---------------------------------------------------------------------------

DEFAULT_PILLARS = [
    (
        "Industry insights",
        "Hot takes, trends, and observations from your domain. The 'I've been thinking about this' posts.",
        30, "#0ea5e9", 1,
    ),
    (
        "Tactical tutorials",
        "Step-by-step how-tos. Anything where the reader walks away able to do something they couldn't before.",
        25, "#10b981", 2,
    ),
    (
        "Personal stories",
        "Lessons learned the hard way. Career milestones. Mistakes that taught you something worth sharing.",
        20, "#f59e0b", 3,
    ),
    (
        "Tools and workflows",
        "What you use, why you use it, what you'd swap out. Reviews, comparisons, setups.",
        15, "#a855f7", 4,
    ),
    (
        "Behind the scenes",
        "The messy middle. Conference travel, side projects, the human stuff people actually relate to.",
        10, "#ef4444", 5,
    ),
]

# Empty by default. The onboarding modal asks new users to paste 3-5 of their
# best past posts so Claude has a real voice to imitate from day one.
DEFAULT_VOICE_SAMPLES: list[tuple[str, str]] = []

DEFAULT_SETTINGS = {
    "creator_name": "",
    "creator_handle": "",
    "creator_bio": "",
    "target_audience": "",
    "default_format": "story",
    "anthropic_api_key": "",
    "weekly_target": "5",
    "preferred_hours": "09:00,12:30,17:30",
}


# ---------------------------------------------------------------------------
# AI helpers
# ---------------------------------------------------------------------------

def get_setting(key: str, default: str = "") -> str:
    with db_cursor() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with db_cursor() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# --- Backend selection: API key vs Claude Code CLI ---------------------------

def is_valid_api_key(k: str | None) -> bool:
    """Reject blanks, placeholders, and obvious junk so the API path doesn't
    spend 401s on values like 'sk-ant-...' that came from a template."""
    if not k:
        return False
    k = k.strip()
    if not k.startswith("sk-ant-"):
        return False
    # Real keys are >40 chars; placeholders are usually <20.
    if len(k) < 30:
        return False
    # Common placeholders contain literal "..." or look like obvious dummies.
    if "..." in k or k.lower().endswith(("-here", "-key")):
        return False
    return True


def auth_status() -> dict:
    """Detect which AI backend is available right now."""
    raw = os.getenv("ANTHROPIC_API_KEY") or get_setting("anthropic_api_key")
    api_key = raw if is_valid_api_key(raw) else ""
    cli_path = shutil.which("claude")
    cli_authed = False
    cli_version = ""
    if cli_path:
        try:
            r = subprocess.run(
                [cli_path, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            cli_version = (r.stdout or "").strip()
            # CLI being on PATH is the strongest signal we have without making a
            # real call. We optimistically treat it as authed; if it's not, the
            # first generation will fail with a clear "claude login" message.
            cli_authed = bool(cli_version)
        except Exception:
            pass

    if api_key:
        provider = "api"
    elif cli_authed:
        provider = "cli"
    else:
        provider = "none"

    return {
        "provider": provider,
        "api_key_set": bool(api_key),
        "cli_installed": bool(cli_path),
        "cli_path": cli_path or "",
        "cli_version": cli_version,
    }


def _call_via_api(system: str, user: str, model: str | None,
                  max_tokens: int | None) -> str:
    if Anthropic is None:
        raise RuntimeError(
            "anthropic SDK is not installed. Run: pip install anthropic"
        )
    raw = os.getenv("ANTHROPIC_API_KEY") or get_setting("anthropic_api_key")
    if not is_valid_api_key(raw):
        raise RuntimeError(
            "Anthropic API key looks invalid (placeholder or wrong format). "
            "Either save a real one in Settings or remove it to use Claude Code CLI."
        )
    client = Anthropic(api_key=raw)
    msg = client.messages.create(
        model=model or DEFAULT_MODEL,
        max_tokens=max_tokens or MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in msg.content if block.type == "text")


def _call_via_cli(system: str, user: str) -> str:
    """Use the local Claude Code CLI. Reuses the user's existing browser auth.

    Critical: we strip any ANTHROPIC_* env vars before invoking the CLI.
    Claude Code prefers an env-var key over its OAuth session, so if the
    parent process has a bad/placeholder key in its env (e.g. loaded from a
    poisoned .env), the CLI will fail too. Stripping forces it to fall back
    to the OAuth session from `claude login`.
    """
    cli_path = shutil.which("claude")
    if not cli_path:
        raise RuntimeError(
            "Claude Code CLI not found on PATH. Install it from "
            "https://docs.claude.com/en/docs/claude-code, then run `claude login`."
        )

    clean_env = {
        k: v for k, v in os.environ.items()
        if not k.startswith("ANTHROPIC_")
    }

    cmd = [
        cli_path,
        "-p", user,
        "--append-system-prompt", system,
        "--output-format", "text",
    ]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, env=clean_env,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"Could not exec claude CLI: {e}")
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        # Common case: not authenticated yet
        if "auth" in msg.lower() or "login" in msg.lower() or "401" in msg:
            raise RuntimeError(
                "Claude Code CLI isn't authenticated. Run `claude login` "
                "in a terminal once, then come back."
            )
        raise RuntimeError(f"claude CLI error: {msg[:300]}")
    return r.stdout


def call_claude(system: str, user: str, model: str | None = None,
                max_tokens: int | None = None, json_mode: bool = False) -> str:
    """Run a single Claude completion via whichever backend is available.

    If the primary backend (API key) errors out with an auth/quota issue,
    we transparently fall back to the Claude Code CLI when it's available.
    """
    status = auth_status()
    text = None
    api_err: Exception | None = None

    if status["provider"] == "api":
        try:
            text = _call_via_api(system, user, model, max_tokens)
        except Exception as e:
            api_err = e
            if status["cli_installed"]:
                text = _call_via_cli(system, user)
            else:
                raise
    elif status["provider"] == "cli":
        text = _call_via_cli(system, user)
    else:
        raise RuntimeError(
            "No AI backend available. Either set an Anthropic API key in "
            "Settings, or install Claude Code and run `claude login` "
            "(https://docs.claude.com/en/docs/claude-code)."
        )

    if json_mode:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            if text.lstrip().lower().startswith("json"):
                text = text.split("\n", 1)[-1]
    return text.strip()


def voice_block() -> str:
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT content FROM voice_samples ORDER BY RANDOM() LIMIT 3"
        ).fetchall()
    if not rows:
        return ""
    samples = "\n\n---\n\n".join(r["content"] for r in rows)
    return f"\n\nVOICE SAMPLES (match this rhythm, sentence length, and energy):\n\n{samples}\n"


def winners_block(pillar_id: int | None = None, limit: int = 3) -> str:
    """Pull the top-performing published posts so the AI can see what's actually
    landing with the audience. Score = likes + 2 * comments (engagement-weighted).
    Restricted to a pillar when one is given so suggestions stay on-niche."""
    with db_cursor() as conn:
        sql = """
            SELECT d.body, d.format, p.name as pillar,
                   COALESCE(SUM(a.likes),0) as likes,
                   COALESCE(SUM(a.comments),0) as comments,
                   COALESCE(SUM(a.likes),0) + 2*COALESCE(SUM(a.comments),0) as score
            FROM drafts d
            JOIN analytics a ON a.draft_id = d.id
            LEFT JOIN pillars p ON p.id = d.pillar_id
            WHERE d.status = 'published'
        """
        params: list = []
        if pillar_id:
            sql += " AND d.pillar_id = ?"
            params.append(pillar_id)
        sql += " GROUP BY d.id HAVING score > 0 ORDER BY score DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, tuple(params)).fetchall()

    if not rows:
        return ""
    parts = [
        "TOP PERFORMERS (these worked — same energy / hooks / structure win):"
    ]
    for r in rows:
        snippet = (r["body"] or "")[:600]
        parts.append(
            f"\n[format: {r['format']} · pillar: {r['pillar'] or 'unassigned'} · "
            f"{r['likes']} likes · {r['comments']} comments]\n{snippet}\n---"
        )
    return "\n".join(parts)


def discarded_block(limit: int = 8) -> str:
    """Recently-rejected ideas. The user said 'no' — don't recycle them."""
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT title FROM ideas WHERE status='discarded' "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    if not rows:
        return ""
    titles = "\n".join(f"- {r['title']}" for r in rows)
    return f"DISCARDED PATTERNS (the user already said no — don't pitch these again):\n{titles}"


def memory_snapshot() -> dict:
    """What is the AI seeing right now?"""
    with db_cursor() as conn:
        winners = conn.execute(
            "SELECT d.id, d.title, d.format, p.name as pillar, "
            "COALESCE(SUM(a.likes),0)+2*COALESCE(SUM(a.comments),0) as score "
            "FROM drafts d JOIN analytics a ON a.draft_id=d.id "
            "LEFT JOIN pillars p ON p.id=d.pillar_id "
            "WHERE d.status='published' "
            "GROUP BY d.id HAVING score > 0 ORDER BY score DESC LIMIT 5"
        ).fetchall()
        voice_n = conn.execute(
            "SELECT COUNT(*) n FROM voice_samples"
        ).fetchone()["n"]
        discarded_n = conn.execute(
            "SELECT COUNT(*) n FROM ideas WHERE status='discarded'"
        ).fetchone()["n"]
        published_n = conn.execute(
            "SELECT COUNT(*) n FROM drafts WHERE status='published'"
        ).fetchone()["n"]
    return {
        "voice_samples": voice_n,
        "published": published_n,
        "discarded": discarded_n,
        "top_performers": [dict(r) for r in winners],
    }


def creator_block() -> str:
    bio = get_setting("creator_bio")
    audience = get_setting("target_audience")
    return textwrap.dedent(f"""
        CREATOR PROFILE:
        {bio}

        TARGET AUDIENCE:
        {audience}
    """).strip()


SYSTEM_BASE = textwrap.dedent("""
    You are a senior LinkedIn ghostwriter who has helped DevOps, cloud, and developer-advocate
    creators grow from zero to 100K+ followers. You write in the creator's voice — never
    yours. You understand what makes posts spread on LinkedIn in 2026: a compelling first
    line, short paragraphs, line breaks for breathing room, a clear point of view, and a
    soft CTA that invites conversation.

    Hard rules:
    • Never use em dashes (—). Use periods or line breaks instead.
    • Never use the words "delve", "leverage", "unlock", "unleash", or "game-changer".
    • Never start a post with "In today's fast-paced world" or any equivalent.
    • Avoid hashtags unless explicitly asked. If used, max 3, lowercase.
    • Each line in the post should be a deliberate beat, not filler.
    • The first line is everything. Make people stop scrolling.
""").strip()


# ---------------------------------------------------------------------------
# Routes — pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — settings
# ---------------------------------------------------------------------------

@app.get("/api/settings")
def api_settings_get():
    with db_cursor() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = {r["key"]: r["value"] for r in rows}
    # Don't ship the actual API key to the frontend; just whether it's set.
    settings.pop("anthropic_api_key", "")
    settings["auth"] = auth_status()
    settings["anthropic_api_key_set"] = settings["auth"]["api_key_set"]
    return jsonify(settings)


@app.get("/api/auth/status")
def api_auth_status():
    return jsonify(auth_status())


@app.post("/api/auth/test")
def api_auth_test():
    """Probe each available backend so the user sees exactly what works."""
    status = auth_status()
    sys_prompt = "You are a health check. Reply with exactly: OK"
    user_prompt = "Say OK."

    used = None
    reply = None
    notes: list[str] = []

    # Try API key first if it's set
    if status["api_key_set"]:
        try:
            reply = _call_via_api(sys_prompt, user_prompt, None, 10)
            used = "api"
        except Exception as e:
            notes.append(f"API key failed: {e}")

    # Fall back to CLI
    if used is None and status["cli_installed"]:
        try:
            reply = _call_via_cli(sys_prompt, user_prompt)
            used = "cli"
        except Exception as e:
            notes.append(f"CLI failed: {e}")

    if used:
        return jsonify({
            "ok": True, "reply": (reply or "").strip(),
            "used": used, "notes": notes, "auth": status,
        })
    return jsonify({
        "ok": False,
        "error": " · ".join(notes) or "No AI backend available.",
        "auth": status,
    })


@app.post("/api/settings/clear-api-key")
def api_settings_clear_api_key():
    set_setting("anthropic_api_key", "")
    return jsonify({"ok": True})


@app.put("/api/settings")
def api_settings_put():
    payload = request.get_json(force=True)
    for k, v in payload.items():
        if k == "anthropic_api_key_set":
            continue
        set_setting(k, str(v))
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Routes — onboarding
#
# First-run flag is "no creator name set". The frontend pings status on boot;
# if first_run, it pops a modal asking for name/handle/bio/audience and
# optionally a few past posts to seed the voice library.
# ---------------------------------------------------------------------------

@app.get("/api/onboarding/status")
def api_onboarding_status():
    return jsonify({
        "first_run": not (get_setting("creator_name") or "").strip(),
        "has_voice_samples": _row_count("voice_samples") > 0,
        "has_pillars": _row_count("pillars") > 0,
    })


@app.post("/api/onboarding/complete")
def api_onboarding_complete():
    payload = request.get_json(force=True)
    profile_keys = ("creator_name", "creator_handle", "creator_bio",
                    "target_audience", "weekly_target", "default_format")
    for k in profile_keys:
        if k in payload:
            set_setting(k, str(payload[k] or ""))
    samples = payload.get("voice_samples") or []
    if samples:
        with db_cursor() as conn:
            for s in samples:
                content = (s.get("content") or "").strip() if isinstance(s, dict) else str(s).strip()
                if not content:
                    continue
                label = (s.get("label") or "seed").strip() if isinstance(s, dict) else "seed"
                conn.execute(
                    "INSERT INTO voice_samples(content, label) VALUES (?, ?)",
                    (content, label),
                )
    return jsonify({"ok": True})


def _row_count(table: str) -> int:
    with db_cursor() as conn:
        return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


# ---------------------------------------------------------------------------
# Routes — backup / migrate
#
# Pure-data dump and restore. JSON, no binary blobs, schema_version included
# so a future restore knows whether the source was older or newer.
# ---------------------------------------------------------------------------

EXPORT_TABLES = (
    "settings", "pillars", "ideas", "drafts", "analytics",
    "voice_samples", "engagement_tasks",
)


def export_to_dict(redact_api_key: bool = True) -> dict:
    payload: dict[str, Any] = {
        "exported_at": datetime.utcnow().isoformat(timespec="seconds"),
        "schema_version": CURRENT_SCHEMA_VERSION,
        "tables": {},
    }
    with db_cursor() as conn:
        for tbl in EXPORT_TABLES:
            rows = conn.execute(f"SELECT * FROM {tbl}").fetchall()
            data = [dict(r) for r in rows]
            if redact_api_key and tbl == "settings":
                for r in data:
                    if r.get("key") == "anthropic_api_key":
                        r["value"] = ""
            payload["tables"][tbl] = data
    return payload


def import_from_dict(payload: dict, *, mode: str = "replace") -> dict:
    """Restore a backup. mode='replace' wipes existing user-data tables first;
    mode='merge' inserts on top of what's there (may produce duplicates).

    schema_version of the backup must be <= current; we don't downgrade."""
    backup_version = int(payload.get("schema_version") or 0)
    if backup_version > CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"Backup is from a newer schema (v{backup_version}); current app is "
            f"v{CURRENT_SCHEMA_VERSION}. Update the app first."
        )
    tables = payload.get("tables") or {}
    counts: dict[str, int] = {}
    with db_cursor() as conn:
        if mode == "replace":
            # Order matters because of FK refs; child tables first.
            for tbl in ("analytics", "engagement_tasks", "drafts",
                        "ideas", "voice_samples", "pillars", "settings"):
                conn.execute(f"DELETE FROM {tbl}")
        for tbl in EXPORT_TABLES:
            rows = tables.get(tbl) or []
            counts[tbl] = 0
            for r in rows:
                cols = list(r.keys())
                placeholders = ",".join("?" for _ in cols)
                col_list = ",".join(cols)
                conn.execute(
                    f"INSERT INTO {tbl}({col_list}) VALUES ({placeholders})",
                    tuple(r[c] for c in cols),
                )
                counts[tbl] += 1
    return {"imported": counts, "from_schema": backup_version}


@app.get("/api/backup/export")
def api_backup_export():
    redact = request.args.get("redact", "1") != "0"
    payload = export_to_dict(redact_api_key=redact)
    fname = f"cadence-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"
    return (
        json.dumps(payload, indent=2, ensure_ascii=False),
        200,
        {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Disposition": f'attachment; filename="{fname}"',
        },
    )


@app.post("/api/backup/import")
def api_backup_import():
    """Body: {payload: {...backup json...}, mode: 'replace' | 'merge'}."""
    body = request.get_json(force=True)
    payload = body.get("payload")
    mode = body.get("mode") or "replace"
    if not isinstance(payload, dict):
        return jsonify({"error": "payload must be a JSON object"}), 400
    if mode not in ("replace", "merge"):
        return jsonify({"error": "mode must be 'replace' or 'merge'"}), 400
    try:
        result = import_from_dict(payload, mode=mode)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, **result})


# ---------------------------------------------------------------------------
# Routes — pillars
# ---------------------------------------------------------------------------

@app.get("/api/pillars")
def api_pillars_get():
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT * FROM pillars ORDER BY sort_order, id"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/pillars")
def api_pillars_create():
    p = request.get_json(force=True)
    with db_cursor() as conn:
        cur = conn.execute(
            "INSERT INTO pillars(name, description, target_pct, color, sort_order) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                p.get("name", "Untitled"),
                p.get("description", ""),
                int(p.get("target_pct", 20)),
                p.get("color", "#6366f1"),
                int(p.get("sort_order", 99)),
            ),
        )
        return jsonify({"id": cur.lastrowid})


@app.put("/api/pillars/<int:pid>")
def api_pillars_update(pid):
    p = request.get_json(force=True)
    fields = ["name", "description", "target_pct", "color", "sort_order"]
    sets = ", ".join(f"{f}=?" for f in fields if f in p)
    values = [p[f] for f in fields if f in p]
    if not sets:
        return jsonify({"ok": True})
    with db_cursor() as conn:
        conn.execute(f"UPDATE pillars SET {sets} WHERE id=?", (*values, pid))
    return jsonify({"ok": True})


@app.delete("/api/pillars/<int:pid>")
def api_pillars_delete(pid):
    with db_cursor() as conn:
        conn.execute("DELETE FROM pillars WHERE id=?", (pid,))
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Routes — ideas
# ---------------------------------------------------------------------------

@app.get("/api/ideas")
def api_ideas_list():
    status = request.args.get("status")
    with db_cursor() as conn:
        if status:
            rows = conn.execute(
                "SELECT i.*, p.name as pillar_name, p.color as pillar_color "
                "FROM ideas i LEFT JOIN pillars p ON p.id=i.pillar_id "
                "WHERE i.status=? ORDER BY i.created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT i.*, p.name as pillar_name, p.color as pillar_color "
                "FROM ideas i LEFT JOIN pillars p ON p.id=i.pillar_id "
                "ORDER BY i.created_at DESC"
            ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/ideas")
def api_ideas_create():
    p = request.get_json(force=True)
    with db_cursor() as conn:
        cur = conn.execute(
            "INSERT INTO ideas(pillar_id, title, hook, angle, source, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                p.get("pillar_id"),
                p.get("title", "Untitled"),
                p.get("hook", ""),
                p.get("angle", ""),
                p.get("source", "manual"),
                p.get("status", "raw"),
            ),
        )
        return jsonify({"id": cur.lastrowid})


@app.put("/api/ideas/<int:iid>")
def api_ideas_update(iid):
    p = request.get_json(force=True)
    fields = ["pillar_id", "title", "hook", "angle", "source", "status"]
    sets = ", ".join(f"{f}=?" for f in fields if f in p)
    values = [p[f] for f in fields if f in p]
    if not sets:
        return jsonify({"ok": True})
    with db_cursor() as conn:
        conn.execute(f"UPDATE ideas SET {sets} WHERE id=?", (*values, iid))
    return jsonify({"ok": True})


@app.delete("/api/ideas/<int:iid>")
def api_ideas_delete(iid):
    with db_cursor() as conn:
        conn.execute("DELETE FROM ideas WHERE id=?", (iid,))
    return jsonify({"ok": True})


@app.post("/api/ideas/generate")
def api_ideas_generate():
    """Generate fresh post ideas, optionally constrained to a pillar / theme."""
    p = request.get_json(force=True)
    pillar_id = p.get("pillar_id")
    theme = (p.get("theme") or "").strip()
    count = int(p.get("count", 5))

    with db_cursor() as conn:
        if pillar_id:
            pillar = conn.execute(
                "SELECT * FROM pillars WHERE id=?", (pillar_id,)
            ).fetchone()
        else:
            pillar = None
        recent = conn.execute(
            "SELECT title FROM ideas ORDER BY created_at DESC LIMIT 20"
        ).fetchall()

    pillar_text = (
        f"\nPILLAR FOCUS:\n{pillar['name']} — {pillar['description']}"
        if pillar else
        "\nNo specific pillar — pick whichever pillar fits each idea best."
    )
    theme_text = f"\nTHEME / TRIGGER: {theme}" if theme else ""
    avoid = "\n".join(f"- {r['title']}" for r in recent) or "(none yet)"

    # Memory injection — winners and discarded patterns
    winners = winners_block(pillar_id=pillar_id, limit=3)
    discarded = discarded_block()
    memory_parts = [b for b in (winners, discarded) if b]
    memory_text = "\n\n".join(memory_parts)

    system = SYSTEM_BASE + "\n\n" + creator_block()
    user = textwrap.dedent(f"""
        Generate {count} LinkedIn post IDEAS for this creator.

        {pillar_text}
        {theme_text}

        AVOID repeating these recent ideas:
        {avoid}

        {memory_text}

        For each idea give:
        - title: 6-10 word working title
        - hook: the actual first line of the post (must stop the scroll)
        - angle: 1-2 sentences on the unique POV / story / data point
        - format: one of [story, list, contrarian, tutorial, bts]

        Return ONLY valid JSON in this shape:
        {{
          "ideas": [
            {{"title": "...", "hook": "...", "angle": "...", "format": "story"}},
            ...
          ]
        }}
    """).strip()

    try:
        text = call_claude(system, user, json_mode=True)
        data = json.loads(text)
        created = []
        with db_cursor() as conn:
            for it in data.get("ideas", []):
                cur = conn.execute(
                    "INSERT INTO ideas(pillar_id, title, hook, angle, source) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        pillar_id,
                        it.get("title", "Untitled")[:200],
                        it.get("hook", ""),
                        it.get("angle", "") + f"\n\n[format: {it.get('format', 'story')}]",
                        "ai",
                    ),
                )
                created.append(cur.lastrowid)
        return jsonify({"ok": True, "created": created, "count": len(created)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Routes — drafts
# ---------------------------------------------------------------------------

@app.get("/api/drafts")
def api_drafts_list():
    status = request.args.get("status")
    with db_cursor() as conn:
        sql = (
            "SELECT d.*, p.name as pillar_name, p.color as pillar_color "
            "FROM drafts d LEFT JOIN pillars p ON p.id=d.pillar_id "
        )
        if status:
            sql += "WHERE d.status=? ORDER BY d.updated_at DESC"
            rows = conn.execute(sql, (status,)).fetchall()
        else:
            sql += "ORDER BY d.updated_at DESC"
            rows = conn.execute(sql).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/drafts/<int:did>")
def api_drafts_get(did):
    with db_cursor() as conn:
        row = conn.execute(
            "SELECT d.*, p.name as pillar_name, p.color as pillar_color "
            "FROM drafts d LEFT JOIN pillars p ON p.id=d.pillar_id "
            "WHERE d.id=?",
            (did,),
        ).fetchone()
    return jsonify(dict(row) if row else None)


@app.post("/api/drafts")
def api_drafts_create():
    p = request.get_json(force=True)
    with db_cursor() as conn:
        cur = conn.execute(
            "INSERT INTO drafts(idea_id, pillar_id, title, body, format, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                p.get("idea_id"),
                p.get("pillar_id"),
                p.get("title", ""),
                p.get("body", ""),
                p.get("format", "story"),
                p.get("status", "draft"),
            ),
        )
        return jsonify({"id": cur.lastrowid})


@app.put("/api/drafts/<int:did>")
def api_drafts_update(did):
    p = request.get_json(force=True)
    p["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    fields = [
        "idea_id", "pillar_id", "title", "body", "format",
        "hook_score", "voice_score", "score_notes", "status",
        "scheduled_for", "posted_at", "updated_at",
    ]
    sets = ", ".join(f"{f}=?" for f in fields if f in p)
    values = [p[f] for f in fields if f in p]
    if not sets:
        return jsonify({"ok": True})
    with db_cursor() as conn:
        conn.execute(f"UPDATE drafts SET {sets} WHERE id=?", (*values, did))
    return jsonify({"ok": True})


@app.delete("/api/drafts/<int:did>")
def api_drafts_delete(did):
    with db_cursor() as conn:
        conn.execute("DELETE FROM drafts WHERE id=?", (did,))
    return jsonify({"ok": True})


FORMAT_GUIDES = {
    "story": (
        "STORY format. Structure: hook line → setup (1-2 lines) → tension/conflict → "
        "turning point → lesson → soft CTA question. 120-220 words. Conversational."
    ),
    "list": (
        "LIST format. Hook line → 1 sentence framing → 5 to 7 numbered items, each 1-3 "
        "lines, parallel grammar → wrap-up line → CTA. Use newline between items."
    ),
    "contrarian": (
        "CONTRARIAN format. Bold first line stating a belief most people hold → "
        "'Here's why they're wrong' → your angle backed by a story or data → reframe → "
        "CTA invite to disagree."
    ),
    "tutorial": (
        "TUTORIAL format. Hook = the painful problem → 'Here's the 4-step fix:' → "
        "numbered steps with concrete commands or actions → result → CTA."
    ),
    "carousel": (
        "CAROUSEL script. Output 8-10 slides as 'Slide 1:', 'Slide 2:'... Slide 1 is a "
        "scroll-stopping hook. Slides 2-8 are one idea each. Slide 9 is summary. Slide "
        "10 is CTA. After the slides, give a 60-90 word LinkedIn caption."
    ),
    "bts": (
        "BEHIND-THE-SCENES format. Vulnerable hook (a moment of doubt, failure, or "
        "surprise) → context → what happened → what you learned → CTA inviting others "
        "to share."
    ),
}


@app.post("/api/drafts/generate")
def api_drafts_generate():
    """Turn an idea (or freeform brief) into a full draft."""
    p = request.get_json(force=True)
    idea_id = p.get("idea_id")
    fmt = p.get("format") or get_setting("default_format", "story")
    extra = (p.get("extra") or "").strip()

    idea = None
    with db_cursor() as conn:
        if idea_id:
            idea = conn.execute(
                "SELECT i.*, p.name as pillar_name FROM ideas i "
                "LEFT JOIN pillars p ON p.id=i.pillar_id WHERE i.id=?",
                (idea_id,),
            ).fetchone()

    brief = ""
    pillar_id = None
    if idea:
        pillar_id = idea["pillar_id"]
        brief = (
            f"TITLE: {idea['title']}\n"
            f"HOOK SEED: {idea['hook'] or '(write your own)'}\n"
            f"ANGLE: {idea['angle'] or '(figure it out)'}\n"
            f"PILLAR: {idea['pillar_name'] or 'general'}\n"
        )
    else:
        brief = p.get("brief", "Open brief. Surprise me.")
        pillar_id = p.get("pillar_id")

    winners = winners_block(pillar_id=pillar_id, limit=2)
    memory_text = f"\n\n{winners}" if winners else ""

    system = SYSTEM_BASE + "\n\n" + creator_block() + voice_block() + memory_text
    user = textwrap.dedent(f"""
        Write ONE LinkedIn post.

        {brief}

        {FORMAT_GUIDES.get(fmt, FORMAT_GUIDES['story'])}

        {('EXTRA INSTRUCTIONS: ' + extra) if extra else ''}

        Output ONLY the post body, ready to paste into LinkedIn. Use real line breaks
        (\\n) between paragraphs and items. No preamble, no commentary, no markdown.
    """).strip()

    try:
        body = call_claude(system, user)
        with db_cursor() as conn:
            cur = conn.execute(
                "INSERT INTO drafts(idea_id, pillar_id, title, body, format, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    idea_id,
                    pillar_id,
                    (idea["title"] if idea else (p.get("title") or "Untitled")),
                    body,
                    fmt,
                    "draft",
                ),
            )
            draft_id = cur.lastrowid
            if idea_id:
                conn.execute(
                    "UPDATE ideas SET status='drafted' WHERE id=?", (idea_id,)
                )
        return jsonify({"ok": True, "id": draft_id, "body": body})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/drafts/<int:did>/rewrite")
def api_drafts_rewrite(did):
    p = request.get_json(force=True)
    instruction = p.get("instruction", "Make it tighter and punchier.")
    with db_cursor() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id=?", (did,)).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Draft not found"}), 404

    system = SYSTEM_BASE + "\n\n" + creator_block() + voice_block()
    user = textwrap.dedent(f"""
        Rewrite this LinkedIn post per the instruction below. Keep the writer's voice.

        ORIGINAL POST:
        ---
        {row['body']}
        ---

        INSTRUCTION:
        {instruction}

        Output ONLY the new post body. No preamble.
    """).strip()

    try:
        new_body = call_claude(system, user)
        with db_cursor() as conn:
            conn.execute(
                "UPDATE drafts SET body=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_body, did),
            )
        return jsonify({"ok": True, "body": new_body})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/drafts/<int:did>/repurpose")
def api_drafts_repurpose(did):
    """Take a published winner and spin out 3 fresh format variants."""
    with db_cursor() as conn:
        row = conn.execute(
            "SELECT d.*, p.name as pillar_name FROM drafts d "
            "LEFT JOIN pillars p ON p.id=d.pillar_id WHERE d.id=?",
            (did,),
        ).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Draft not found"}), 404

    system = SYSTEM_BASE + "\n\n" + creator_block() + voice_block()
    user = textwrap.dedent(f"""
        This LinkedIn post landed. Generate 3 NEW posts that ride the same
        winning idea but feel completely fresh — different format, different hook,
        different angle on the same insight. Don't paraphrase. Re-imagine.

        ORIGINAL POST:
        ---
        {row['body']}
        ---

        Each variant must use a DIFFERENT format from this set:
        story, list, contrarian, tutorial, bts.

        Return ONLY valid JSON:
        {{"variants": [
          {{"format": "list", "title": "6-10 word working title", "body": "the full post"}},
          {{"format": "...", "title": "...", "body": "..."}},
          {{"format": "...", "title": "...", "body": "..."}}
        ]}}
    """).strip()

    try:
        text = call_claude(system, user, json_mode=True, max_tokens=2400)
        data = json.loads(text)
        created = []
        with db_cursor() as conn:
            for v in data.get("variants", []):
                cur = conn.execute(
                    "INSERT INTO drafts(pillar_id, title, body, format, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        row["pillar_id"],
                        (v.get("title") or "Repurpose")[:200],
                        v.get("body", ""),
                        v.get("format", "story"),
                        "draft",
                    ),
                )
                created.append(cur.lastrowid)
        return jsonify({"ok": True, "created": created, "count": len(created)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/memory")
def api_memory():
    """What context the AI is currently drawing from."""
    return jsonify(memory_snapshot())


@app.post("/api/drafts/<int:did>/score")
def api_drafts_score(did):
    with db_cursor() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id=?", (did,)).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Draft not found"}), 404

    system = SYSTEM_BASE + "\n\n" + creator_block() + voice_block()
    user = textwrap.dedent(f"""
        Score this LinkedIn post on TWO dimensions, 1-10 integer each.

        1. HOOK STRENGTH (does the first line stop the scroll?)
           - 10 = unmissable, specific, emotional, contrarian or curiosity-driven
           - 5  = generic but not bad
           - 1  = puts the reader to sleep

        2. VOICE MATCH (does it sound like the creator's samples above?)
           - 10 = indistinguishable from the samples
           - 5  = on-topic but bland / generic LinkedIn voice
           - 1  = sounds AI-generated

        Then give 3 short, concrete improvement notes (one line each).

        POST:
        ---
        {row['body']}
        ---

        Return ONLY valid JSON:
        {{"hook_score": 0, "voice_score": 0, "notes": ["...","...","..."]}}
    """).strip()

    try:
        text = call_claude(system, user, json_mode=True, max_tokens=600)
        data = json.loads(text)
        notes = " • ".join(data.get("notes", []))
        with db_cursor() as conn:
            conn.execute(
                "UPDATE drafts SET hook_score=?, voice_score=?, score_notes=? "
                "WHERE id=?",
                (
                    int(data.get("hook_score", 0)),
                    int(data.get("voice_score", 0)),
                    notes,
                    did,
                ),
            )
        return jsonify({"ok": True, **data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Routes — calendar / scheduling
# ---------------------------------------------------------------------------

@app.get("/api/calendar")
def api_calendar():
    start = request.args.get("start")
    end = request.args.get("end")
    with db_cursor() as conn:
        if start and end:
            rows = conn.execute(
                "SELECT d.*, p.name as pillar_name, p.color as pillar_color "
                "FROM drafts d LEFT JOIN pillars p ON p.id=d.pillar_id "
                "WHERE d.scheduled_for IS NOT NULL "
                "AND d.scheduled_for BETWEEN ? AND ? "
                "ORDER BY d.scheduled_for ASC",
                (start, end),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT d.*, p.name as pillar_name, p.color as pillar_color "
                "FROM drafts d LEFT JOIN pillars p ON p.id=d.pillar_id "
                "WHERE d.scheduled_for IS NOT NULL "
                "ORDER BY d.scheduled_for ASC"
            ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/calendar/auto-schedule")
def api_calendar_auto_schedule():
    """
    Pick READY drafts and schedule them across the next N days, respecting
    pillar percentages and preferred posting hours.
    """
    p = request.get_json(force=True)
    days = int(p.get("days", 14))
    target_per_week = int(get_setting("weekly_target", "5") or "5")
    hours = [
        h.strip() for h in (get_setting("preferred_hours", "09:00,17:30")).split(",")
        if h.strip()
    ] or ["09:00"]

    with db_cursor() as conn:
        ready = conn.execute(
            "SELECT * FROM drafts WHERE status IN ('draft','ready') "
            "AND scheduled_for IS NULL ORDER BY updated_at DESC"
        ).fetchall()
        pillars = {
            r["id"]: r for r in
            conn.execute("SELECT * FROM pillars").fetchall()
        }

    if not ready:
        return jsonify({"ok": True, "scheduled": 0, "message": "No drafts ready."})

    # Build slots: every ~ (7/target_per_week) days at preferred hours
    slot_dates = []
    today = date.today()
    interval = max(1, round(7 / max(1, target_per_week)))
    cur = today
    while cur <= today + timedelta(days=days):
        if cur.weekday() < 5:  # weekdays only
            slot_dates.append(cur)
        cur += timedelta(days=interval)

    slots: list[datetime] = []
    for d in slot_dates:
        for h in hours:
            try:
                hh, mm = h.split(":")
                slots.append(datetime(d.year, d.month, d.day, int(hh), int(mm)))
            except ValueError:
                continue
    slots = slots[: len(ready)]

    # Order drafts to spread pillars
    by_pillar: dict[int | None, list] = {}
    for d in ready:
        by_pillar.setdefault(d["pillar_id"], []).append(d)
    interleaved = []
    while any(by_pillar.values()):
        for pid in list(by_pillar.keys()):
            if by_pillar[pid]:
                interleaved.append(by_pillar[pid].pop(0))

    scheduled = 0
    with db_cursor() as conn:
        for draft, slot in zip(interleaved, slots):
            conn.execute(
                "UPDATE drafts SET status='scheduled', scheduled_for=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (slot.isoformat(timespec="minutes"), draft["id"]),
            )
            scheduled += 1
    return jsonify({"ok": True, "scheduled": scheduled})


# ---------------------------------------------------------------------------
# Routes — analytics
# ---------------------------------------------------------------------------

@app.get("/api/analytics")
def api_analytics_list():
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT a.*, d.title as draft_title, d.body as draft_body, "
            "d.posted_at as posted_at, p.name as pillar_name, p.color as pillar_color "
            "FROM analytics a "
            "JOIN drafts d ON d.id = a.draft_id "
            "LEFT JOIN pillars p ON p.id = d.pillar_id "
            "ORDER BY a.recorded_at DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/analytics")
def api_analytics_create():
    p = request.get_json(force=True)
    with db_cursor() as conn:
        cur = conn.execute(
            "INSERT INTO analytics(draft_id, impressions, likes, comments, "
            "reposts, follows, profile_visits) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                int(p["draft_id"]),
                int(p.get("impressions", 0) or 0),
                int(p.get("likes", 0) or 0),
                int(p.get("comments", 0) or 0),
                int(p.get("reposts", 0) or 0),
                int(p.get("follows", 0) or 0),
                int(p.get("profile_visits", 0) or 0),
            ),
        )
        # mark draft published if not already
        conn.execute(
            "UPDATE drafts SET status='published', "
            "posted_at = COALESCE(posted_at, CURRENT_TIMESTAMP) WHERE id=?",
            (int(p["draft_id"]),),
        )
        return jsonify({"id": cur.lastrowid})


def _xlsx_read_all_sheets(xlsx_bytes: bytes) -> list[dict]:
    """Read every sheet in the workbook, score each by post-analytics signal,
    return them sorted best-first. Each entry has: name, score, rows (csv text),
    row_count, preview (first 5 non-blank rows as list-of-list)."""
    import csv as _csv
    import io
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise RuntimeError("openpyxl not installed. Run: pip install openpyxl")

    # IMPORTANT: don't use read_only=True. LinkedIn's xlsx exports omit or
    # misreport the <dimension> tag, which read-only mode trusts blindly,
    # causing openpyxl to see only the top-left cell of each sheet.
    wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    keywords = (
        "impression", "view", "like", "reaction", "comment",
        "repost", "share", "engagement", "click", "post url", "post text",
        "post title", "follower", "created date", "published",
    )

    def cell_str(v) -> str:
        if v is None:
            return ""
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)

    sheets = []
    for name in wb.sheetnames:
        ws = wb[name]
        rows: list[list[str]] = []
        # Iterate by explicit max_row/max_column to be robust against dimension
        # weirdness. ws.max_row/max_column reflect actual cell content even if
        # the dimension XML lies.
        max_r = ws.max_row or 0
        max_c = ws.max_column or 0
        for r in range(1, max_r + 1):
            cells = [cell_str(ws.cell(row=r, column=c).value)
                     for c in range(1, max_c + 1)]
            if any(c.strip() for c in cells):
                rows.append(cells)
        if not rows:
            continue
        buf = io.StringIO()
        w = _csv.writer(buf)
        for r in rows:
            w.writerow(r)
        sheet_csv = buf.getvalue()
        low = sheet_csv.lower()
        score = sum(low.count(k) for k in keywords)
        nm = name.lower()
        if "post" in nm or "top" in nm:
            score += 50
        if "discovery" in nm or "engagement" in nm:
            score += 10
        if "follower" in nm or "demographic" in nm or "summary" in nm:
            score -= 5
        if len(rows) < 2:
            score -= 30
        sheets.append({
            "name": name,
            "score": score,
            "csv": sheet_csv,
            "row_count": len(rows),
            "preview": rows[:5],
        })

    sheets.sort(key=lambda s: s["score"], reverse=True)
    return sheets


@app.post("/api/analytics/import-preview")
def api_analytics_import_preview():
    """
    Parse a LinkedIn analytics export (CSV or XLSX) and auto-match each row
    to an existing draft by body-snippet or date. The frontend shows the
    result and lets the user confirm or override.
    """
    import csv as _csv
    import io
    import base64
    payload = request.get_json(force=True)
    csv_text = payload.get("csv", "")
    xlsx_b64 = payload.get("xlsx", "")

    chosen_sheet = ""
    sheets_available: list[str] = []
    sheet_override = (payload.get("sheet_override") or "").strip()
    sheets_meta: list[dict] = []

    if xlsx_b64:
        try:
            xlsx_bytes = base64.b64decode(xlsx_b64)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Bad base64 xlsx: {e}"}), 400
        try:
            sheets_meta = _xlsx_read_all_sheets(xlsx_bytes)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        if not sheets_meta:
            return jsonify({"ok": False, "error": "No non-empty sheets in workbook"}), 400
        sheets_available = [s["name"] for s in sheets_meta]

        # If user picked a specific sheet, honor that. Otherwise use highest score.
        chosen = None
        if sheet_override:
            for s in sheets_meta:
                if s["name"] == sheet_override:
                    chosen = s
                    break
        if chosen is None:
            chosen = sheets_meta[0]
        csv_text = chosen["csv"]
        chosen_sheet = chosen["name"]

    if not csv_text or not csv_text.strip():
        return jsonify({"ok": False, "error": "Empty file"}), 400

    # Some LinkedIn exports prefix the actual table with a title row, a blank
    # line, a generated-on timestamp, etc. Look for the first row that smells
    # like a header (multiple columns, contains an analytics keyword OR contains
    # a "post"/"date"/"url" word). If nothing matches, just take the first
    # non-blank row as the header.
    raw_reader = _csv.reader(io.StringIO(csv_text))
    all_rows = [r for r in raw_reader if any((c or "").strip() for c in r)]

    HEADER_KEYWORDS = (
        "impression", "view", "like", "reaction", "comment",
        "repost", "share", "engagement", "click",
        "post url", "post text", "post title", "post link",
        "created date", "published", "date posted", "posted on",
    )
    header_idx = -1
    for i, r in enumerate(all_rows):
        joined = ",".join((c or "").lower() for c in r)
        if len(r) >= 2 and any(k in joined for k in HEADER_KEYWORDS):
            header_idx = i
            break
    if header_idx == -1:
        # No header keyword found. Take the first multi-column row as header.
        for i, r in enumerate(all_rows):
            if len(r) >= 2:
                header_idx = i
                break
    if header_idx == -1:
        # Truly nothing to work with. If this came from xlsx, show all sheets
        # so the user can pick a different one manually.
        previews = [
            {"name": s["name"], "row_count": s["row_count"],
             "score": s["score"], "preview": s["preview"]}
            for s in sheets_meta
        ] if sheets_meta else []
        return jsonify({
            "ok": False,
            "error": "Could not find a usable header row.",
            "sheet_used": chosen_sheet,
            "sheets_preview": previews,
        }), 400

    rows = all_rows[header_idx:]
    if len(rows) < 2:
        previews = [
            {"name": s["name"], "row_count": s["row_count"],
             "score": s["score"], "preview": s["preview"]}
            for s in sheets_meta
        ] if sheets_meta else []
        return jsonify({
            "ok": False,
            "error": (f"Sheet '{chosen_sheet}' has a header but no data rows."
                      if chosen_sheet else
                      "Need a header and at least one data row."),
            "sheet_used": chosen_sheet,
            "sheets_preview": previews,
        }), 400

    headers_raw = rows[0]
    headers = [(h or "").strip().lower() for h in headers_raw]

    def find_col(*candidates: str) -> int:
        for cand in candidates:
            for i, h in enumerate(headers):
                if cand in h:
                    return i
        return -1

    col = {
        "date":     find_col("date", "created", "posted", "publish"),
        "impr":     find_col("impression", "view"),
        "likes":    find_col("reaction", "like"),
        "comments": find_col("comment"),
        "reposts":  find_col("repost", "share"),
        "follows":  find_col("follow"),
        "url":      find_col("url", "link"),
        "text":     find_col("post text", "post title", "caption",
                             "message", "content", "body", "text"),
    }

    with db_cursor() as conn:
        drafts = conn.execute(
            "SELECT id, body, posted_at, scheduled_for, title, status "
            "FROM drafts ORDER BY id DESC"
        ).fetchall()

    def to_int(s: str) -> int:
        s = (s or "").strip().replace(",", "")
        if not s:
            return 0
        # tolerate "1.2K" / "1,234" / floats
        try:
            if s.lower().endswith("k"):
                return int(float(s[:-1]) * 1000)
            return int(float(s))
        except ValueError:
            return 0

    def parse_iso(s: str):
        if not s:
            return None
        s = s.strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%b %d, %Y"):
            try:
                return datetime.strptime(s[:25].split("T")[0], fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s[:25])
        except ValueError:
            return None

    parsed: list[dict] = []
    for i, row in enumerate(rows[1:]):
        def g(idx: int) -> str:
            return (row[idx] or "").strip() if 0 <= idx < len(row) else ""
        parsed.append({
            "row_idx": i,
            "date": g(col["date"]),
            "snippet": g(col["text"])[:120],
            "url": g(col["url"]),
            "impressions": to_int(g(col["impr"])),
            "likes":       to_int(g(col["likes"])),
            "comments":    to_int(g(col["comments"])),
            "reposts":     to_int(g(col["reposts"])),
            "follows":     to_int(g(col["follows"])),
            "matched_draft_id": None,
            "match_reason": "",
        })

    # Pass 1: snippet match (high confidence). Each draft can only claim one row.
    claimed: set[int] = set()
    for item in parsed:
        snip = (item["snippet"] or "").lower()[:35]
        if not snip:
            continue
        for d in drafts:
            if d["id"] in claimed:
                continue
            body = (d["body"] or "").lower()
            if snip and snip in body:
                item["matched_draft_id"] = d["id"]
                item["match_reason"] = "snippet"
                claimed.add(d["id"])
                break

    # Pass 2: date proximity for still-unmatched rows, against still-unclaimed drafts.
    for item in parsed:
        if item["matched_draft_id"]:
            continue
        post_date = parse_iso(item["date"])
        if not post_date:
            continue
        best = None
        best_delta = 99999
        for d in drafts:
            if d["id"] in claimed:
                continue
            for fld in ("posted_at", "scheduled_for"):
                v = d[fld]
                if not v:
                    continue
                dd = parse_iso(v)
                if not dd:
                    continue
                delta = abs((post_date - dd).days)
                if delta <= 3 and delta < best_delta:
                    best, best_delta = d["id"], delta
        if best:
            item["matched_draft_id"] = best
            item["match_reason"] = f"date(±{best_delta}d)"
            claimed.add(best)

    sheets_preview = [
        {"name": s["name"], "row_count": s["row_count"],
         "score": s["score"], "preview": s["preview"]}
        for s in sheets_meta
    ] if sheets_meta else []

    return jsonify({
        "ok": True,
        "headers": headers_raw,
        "detected": col,
        "parsed": parsed,
        "sheet_used": chosen_sheet,
        "sheets_available": sheets_available,
        "sheets_preview": sheets_preview,
        "drafts": [
            {"id": d["id"], "title": d["title"] or "",
             "preview": (d["body"] or "")[:80], "status": d["status"]}
            for d in drafts
        ],
    })


@app.post("/api/analytics/import-commit")
def api_analytics_import_commit():
    """Insert the user-confirmed rows. Skips any row without a draft_id."""
    payload = request.get_json(force=True)
    rows = payload.get("rows", [])
    created = 0
    skipped = 0
    with db_cursor() as conn:
        for r in rows:
            did = r.get("draft_id")
            if not did:
                skipped += 1
                continue
            conn.execute(
                "INSERT INTO analytics(draft_id, impressions, likes, comments, "
                "reposts, follows) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    int(did),
                    int(r.get("impressions", 0) or 0),
                    int(r.get("likes", 0) or 0),
                    int(r.get("comments", 0) or 0),
                    int(r.get("reposts", 0) or 0),
                    int(r.get("follows", 0) or 0),
                ),
            )
            conn.execute(
                "UPDATE drafts SET status='published', "
                "posted_at = COALESCE(posted_at, CURRENT_TIMESTAMP) WHERE id=?",
                (int(did),),
            )
            created += 1
    return jsonify({"ok": True, "created": created, "skipped": skipped})


@app.get("/api/analytics/insights")
def api_analytics_insights():
    """Roll up analytics + ask Claude what's working."""
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT d.id, d.title, d.format, p.name as pillar, "
            "SUM(a.impressions) impressions, SUM(a.likes) likes, "
            "SUM(a.comments) comments, SUM(a.follows) follows "
            "FROM analytics a JOIN drafts d ON d.id=a.draft_id "
            "LEFT JOIN pillars p ON p.id=d.pillar_id "
            "GROUP BY d.id ORDER BY likes DESC LIMIT 30"
        ).fetchall()

    if not rows:
        return jsonify({"insight": "Log some analytics first, then I'll spot patterns."})

    table = "title | format | pillar | impr | likes | comments | follows\n"
    for r in rows:
        table += (
            f"{(r['title'] or '')[:60]} | {r['format']} | {r['pillar']} | "
            f"{r['impressions']} | {r['likes']} | {r['comments']} | {r['follows']}\n"
        )

    system = SYSTEM_BASE + "\n\n" + creator_block()
    user = textwrap.dedent(f"""
        Here is the creator's recent post performance.

        {table}

        Give 5 SHORT, specific, actionable insights:
        - Which pillar is overperforming and why
        - Which format is winning
        - Which topics to do MORE of
        - What pattern in their hooks works best
        - One concrete experiment to run next week

        Use plain prose, max 6 lines total. No bullet markers.
    """).strip()

    try:
        text = call_claude(system, user, max_tokens=600)
        return jsonify({"insight": text})
    except Exception as e:
        return jsonify({"insight": f"Could not run insights: {e}"})


# ---------------------------------------------------------------------------
# Routes — engagement
# ---------------------------------------------------------------------------

@app.get("/api/engagement")
def api_engagement_list():
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT * FROM engagement_tasks ORDER BY completed ASC, due_date ASC, id DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/engagement")
def api_engagement_create():
    p = request.get_json(force=True)
    with db_cursor() as conn:
        cur = conn.execute(
            "INSERT INTO engagement_tasks(draft_id, type, details, due_date) "
            "VALUES (?, ?, ?, ?)",
            (
                p.get("draft_id"),
                p.get("type", "comment"),
                p.get("details", ""),
                p.get("due_date"),
            ),
        )
        return jsonify({"id": cur.lastrowid})


@app.put("/api/engagement/<int:eid>")
def api_engagement_update(eid):
    p = request.get_json(force=True)
    fields = ["type", "details", "due_date", "completed"]
    sets = ", ".join(f"{f}=?" for f in fields if f in p)
    values = [p[f] for f in fields if f in p]
    if not sets:
        return jsonify({"ok": True})
    with db_cursor() as conn:
        conn.execute(f"UPDATE engagement_tasks SET {sets} WHERE id=?", (*values, eid))
    return jsonify({"ok": True})


@app.delete("/api/engagement/<int:eid>")
def api_engagement_delete(eid):
    with db_cursor() as conn:
        conn.execute("DELETE FROM engagement_tasks WHERE id=?", (eid,))
    return jsonify({"ok": True})


@app.post("/api/engagement/comments")
def api_engagement_comments():
    """Generate 3 thoughtful comment templates for a target post snippet."""
    p = request.get_json(force=True)
    target = p.get("target_post", "")
    if not target.strip():
        return jsonify({"ok": False, "error": "Provide target_post"}), 400

    system = SYSTEM_BASE + "\n\n" + creator_block()
    user = textwrap.dedent(f"""
        Write 3 short LinkedIn comments to leave on this post. Each comment must:
        - Add value (specific story, example, or counterpoint)
        - Sound like the creator
        - Be 2-4 lines max
        - Not be sycophantic ("great post!" / "amazing!" — banned)

        TARGET POST:
        ---
        {target}
        ---

        Return ONLY JSON: {{"comments": ["...","...","..."]}}
    """).strip()
    try:
        text = call_claude(system, user, json_mode=True, max_tokens=600)
        return jsonify({"ok": True, **json.loads(text)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Routes — voice samples
# ---------------------------------------------------------------------------

@app.get("/api/voice")
def api_voice_list():
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT * FROM voice_samples ORDER BY id DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/voice")
def api_voice_create():
    p = request.get_json(force=True)
    with db_cursor() as conn:
        cur = conn.execute(
            "INSERT INTO voice_samples(content, label) VALUES (?, ?)",
            (p.get("content", ""), p.get("label", "")),
        )
        return jsonify({"id": cur.lastrowid})


@app.delete("/api/voice/<int:vid>")
def api_voice_delete(vid):
    with db_cursor() as conn:
        conn.execute("DELETE FROM voice_samples WHERE id=?", (vid,))
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Routes — dashboard
# ---------------------------------------------------------------------------

@app.get("/api/dashboard")
def api_dashboard():
    with db_cursor() as conn:
        ideas_raw = conn.execute(
            "SELECT COUNT(*) n FROM ideas WHERE status='raw'"
        ).fetchone()["n"]
        drafts_n = conn.execute(
            "SELECT COUNT(*) n FROM drafts WHERE status IN ('draft','ready')"
        ).fetchone()["n"]
        scheduled_n = conn.execute(
            "SELECT COUNT(*) n FROM drafts WHERE status='scheduled'"
        ).fetchone()["n"]
        published_n = conn.execute(
            "SELECT COUNT(*) n FROM drafts WHERE status='published'"
        ).fetchone()["n"]
        next_up = conn.execute(
            "SELECT d.id, d.title, d.scheduled_for, p.name as pillar_name, p.color as pillar_color "
            "FROM drafts d LEFT JOIN pillars p ON p.id=d.pillar_id "
            "WHERE d.status='scheduled' AND d.scheduled_for >= datetime('now') "
            "ORDER BY d.scheduled_for ASC LIMIT 5"
        ).fetchall()
        totals = conn.execute(
            "SELECT COALESCE(SUM(impressions),0) i, COALESCE(SUM(likes),0) l, "
            "COALESCE(SUM(comments),0) c, COALESCE(SUM(follows),0) f "
            "FROM analytics"
        ).fetchone()
        pillar_mix = conn.execute(
            "SELECT p.name, p.color, COUNT(d.id) n "
            "FROM pillars p LEFT JOIN drafts d ON d.pillar_id=p.id "
            "AND d.status='published' GROUP BY p.id ORDER BY p.sort_order"
        ).fetchall()
    return jsonify({
        "counts": {
            "ideas_raw": ideas_raw,
            "drafts": drafts_n,
            "scheduled": scheduled_n,
            "published": published_n,
        },
        "next_up": [dict(r) for r in next_up],
        "totals": dict(totals),
        "pillar_mix": [dict(r) for r in pillar_mix],
    })


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

init_db()


def _cli_export(path: str, *, include_api_key: bool) -> int:
    payload = export_to_dict(redact_api_key=not include_api_key)
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    totals = {t: len(payload["tables"][t]) for t in EXPORT_TABLES}
    print(f"Exported {sum(totals.values())} rows to {path}")
    for t, n in totals.items():
        print(f"  {t}: {n}")
    if include_api_key:
        print("WARNING: --include-api-key was set. Treat this file as a secret.")
    return 0


def _cli_import(path: str, *, mode: str, yes: bool) -> int:
    p = Path(path)
    if not p.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 2
    payload = json.loads(p.read_text(encoding="utf-8"))
    if mode == "replace" and not yes:
        print("This will DELETE all current data and replace it with the backup.")
        confirm = input("Type 'yes' to continue: ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            return 1
    try:
        result = import_from_dict(payload, mode=mode)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    total = sum(result["imported"].values())
    print(f"Imported {total} rows from {path} (mode={mode}).")
    for t, n in result["imported"].items():
        print(f"  {t}: {n}")
    return 0


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cadence — run the server, or back up / restore your data.",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_export = sub.add_parser("export", help="Dump all data to a JSON file.")
    p_export.add_argument("path", help="Output JSON path (e.g. backup.json)")
    p_export.add_argument(
        "--include-api-key", action="store_true",
        help="Include the saved Anthropic API key in the dump (default: redacted).",
    )

    p_import = sub.add_parser("import", help="Restore from a JSON backup.")
    p_import.add_argument("path", help="Backup JSON path")
    p_import.add_argument(
        "--mode", choices=("replace", "merge"), default="replace",
        help="replace = wipe current data first; merge = insert on top.",
    )
    p_import.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation prompt.",
    )

    sub.add_parser("serve", help="Start the web server (default).")
    return parser


if __name__ == "__main__":
    parser = _build_cli()
    args = parser.parse_args()
    if args.cmd == "export":
        sys.exit(_cli_export(args.path, include_api_key=args.include_api_key))
    if args.cmd == "import":
        sys.exit(_cli_import(args.path, mode=args.mode, yes=args.yes))
    # Default: serve
    port = int(os.getenv("PORT", "5050"))
    print(f"\n  Cadence running at http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=True)
