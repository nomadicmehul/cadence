# Cadence

A self-hosted, single-user LinkedIn growth tool powered by Claude. Turns the
chaos of "what should I post next?" into a repeatable pipeline:

```
 Ideas  →  Drafts  →  Scheduled  →  Published  →  Analytics  →  Repurpose
```

Runs on your laptop. Your data lives in one SQLite file (`data/pipeline.db`).
Nothing leaves your machine except the prompts you send to Claude.

> Built originally for one creator's workflow, now generalised so anyone can
> drop in their own voice, pillars, and audience in 60 seconds of onboarding.

---

## Quick start

```bash
git clone https://github.com/<your-fork>/cadence.git
cd cadence
chmod +x run.sh
./run.sh
```

Open **http://127.0.0.1:5050**. The first time you load the app, an
onboarding modal asks for your name, bio, target audience, and 3 of your
best past posts so Claude can imitate your voice from day one.

### Authentication (pick one)

The tool **auto-detects** which AI backend is available, in this priority:

1. **Anthropic API key** — set `ANTHROPIC_API_KEY` in `.env`, or paste it in
   **Settings → AI backend**. ([Get one ↗](https://console.anthropic.com/))
2. **Claude Code CLI** *(no API key needed)* — install
   [Claude Code](https://docs.claude.com/en/docs/claude-code) and run
   `claude login` once. The tool re-uses that browser-OAuth session via
   subprocess.

The top-bar pill shows which backend is live ("Claude (API key)" or
"Claude (CLI)"). Hit **Test connection** in Settings to verify.

### Manual install (if `run.sh` doesn't fit your setup)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

---

## Migrating to a new computer

The whole app's state lives in `data/pipeline.db`. There are two ways to move it.

### Option A — JSON backup (recommended)

On the **old** machine:

```bash
# From the project root
python app.py export ~/Desktop/cadence-backup.json
# Or click "Download backup" in Settings → Backup & migrate
```

The export is human-readable JSON. By default it **strips your Anthropic API
key** (paste it again on the new machine). Pass `--include-api-key` if you're
moving to a trusted machine and don't want to re-paste.

On the **new** machine:

```bash
git clone https://github.com/<your-fork>/cadence.git
cd cadence
./run.sh                                 # creates DB with default seeds
# stop the server (Ctrl-C), then:
python app.py import ~/Desktop/cadence-backup.json
./run.sh                                 # restart — your data is back
```

Or use the UI: **Settings → Backup & migrate → Restore from backup**, pick
the JSON file. Confirms with a "this wipes current data" prompt, then reloads.

### Option B — copy the SQLite file

If you trust both machines and don't need the JSON-readable history:

```bash
# On old machine, after stopping the server
scp data/pipeline.db newmachine:~/cadence/data/pipeline.db
```

Then start the app on the new machine. Schema migrations run automatically on
boot; if the new app version added columns, your old DB picks them up
gracefully.

> Don't copy `data/pipeline.db` while the server is running — SQLite may
> have an open write transaction. Stop the server first, or use Option A.

---

## What's inside

| Tab | What it does |
|---|---|
| **Dashboard** | Pipeline counts, what's up next, pillar mix, all-time engagement totals, "Memory snapshot" card showing exactly what context the AI sees. |
| **Ideas** | Generate batches of ideas with Claude (hook + angle + format). Filter by pillar/status. Convert any idea into a draft in one click. |
| **Drafts** | Split-pane composer. Generate, rewrite ("tighter", "more contrarian"), score (Hook 1-10 / Voice 1-10), copy to clipboard, schedule. |
| **Calendar** | Month grid of scheduled posts. **Auto-schedule** spreads ready drafts across weekdays at your preferred hours, balanced by pillar. |
| **Analytics** | Log impressions/likes/comments/follows per published post. Import LinkedIn's Creator Analytics xlsx export — auto-matches rows to your drafts. **What's working?** gives a one-paragraph Claude analysis. |
| **Engagement** | Task list for comments + follow-ups. Comment generator writes 3 thoughtful comments for any post you paste in. |
| **Voice** | Library of your past posts. Claude samples 3 at random for every generation, so the AI writes in *your* rhythm — not generic AI prose. |
| **Settings** | API key, creator profile, pillars (with target % and color), backup/restore. |

---

## How publishing works

There's no LinkedIn API for personal post analytics, so this tool intentionally
sits one step away: every draft has a **Copy to clipboard** button that gives
you the post exactly as it should appear on LinkedIn. Paste, post, then come
back and log the numbers in **Analytics** (or import the xlsx).

The xlsx importer does fuzzy matching: it auto-pairs CSV rows to existing
drafts by body-snippet similarity first, falling back to date proximity.

---

## Tech

- **Backend**: Flask + SQLite, single file (`app.py`)
- **AI**: Anthropic SDK with Claude Sonnet 4.5 by default (override with
  `CLAUDE_MODEL` env var)
- **Frontend**: Vanilla JS, no build step
- **Tests**: `pytest` smoke suite, runs in CI on Python 3.10 / 3.11 / 3.12

All AI prompts live in `app.py` so you can tune them. The `SYSTEM_BASE`
constant defines the writing rules (no em-dashes, banned filler words, etc.)
and is combined with your live voice samples on every call.

---

## Contributing

PRs welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first — there are some
hard constraints (no build step, no new heavy deps without discussion).

For security issues, email mehul.patel@buildingminds.com — see
[SECURITY.md](SECURITY.md).

---

## License

MIT. See [LICENSE](LICENSE).
