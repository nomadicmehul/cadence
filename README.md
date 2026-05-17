# Cadence

A self-hosted, single-user LinkedIn growth tool powered by Claude. Turns the
chaos of "what should I post next?" into a repeatable pipeline:

```
 Ideas  →  Drafts  →  Scheduled  →  Published  →  Analytics  →  Repurpose
```

Runs on your laptop. Your data lives in one SQLite file (`data/pipeline.db`).
Nothing leaves your machine except the prompts you send to Claude.

**Live site:** [nomadicmehul.github.io/cadence](https://nomadicmehul.github.io/cadence/) (project showcase, no install needed)

> Built originally for one creator's workflow, now generalised so anyone can
> drop in their own voice, pillars, and audience in 60 seconds of onboarding.

---

## Quick start

```bash
git clone https://github.com/nomadicmehul/cadence.git
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
git clone https://github.com/nomadicmehul/cadence.git
cd cadence
./run.sh                                 # creates DB with default seeds
# stop the server (Ctrl-C), then:
python app.py import ~/Desktop/cadence-backup.json
./run.sh                                 # restart — your data is back
```

Or use the UI: **Settings → Backup & migrate → Restore from backup**, pick
the JSON file. Confirms with a "this wipes current data" prompt, then reloads.

### Option B — `profile.md` (just the creator profile, human-editable)

For your settings, content pillars, voice samples, and topic sources — a
markdown file is friendlier to version-control and edit in any text editor.

```bash
# Export
python app.py profile export ~/Desktop/profile.md
# Or click "Save to profile.md" in Settings → Creator profile

# Edit freely — plain markdown with YAML-style frontmatter

# Load back
python app.py profile import ~/Desktop/profile.md
# Or click "Load from file…" in Settings → Creator profile
```

Import is **additive**: pillars and topic sources upsert by name / URL,
voice samples append (no duplicates), nothing in the DB is deleted just
because it's missing from the file. Use Option A for a full wipe-and-replace.

### Option C — full backup as a `.zip` of markdown files (human-editable)

Same data as Option A, but each draft / idea / reflection is its own
readable file in a zip. Edit individual posts in any text editor, commit
the folder to git for version-controlled history.

```bash
# Export
python app.py backup export-md ~/Desktop/cadence-backup.zip
# Or click "Download backup (.zip)" in Settings → Backup & migrate

# Unzip, edit any file in your text editor, re-zip

# Load back
python app.py backup import-md ~/Desktop/cadence-backup.zip
# Or click "Restore from .zip…" in Settings → Backup & migrate
```

Archive layout:

```
cadence-backup-YYYYMMDD/
├── profile.md            # creator profile (Option B's file)
├── drafts/
│   └── 0042-some-title.md
├── ideas.md
├── reflections.md
├── topics.md
├── analytics.csv         # tabular data stays tabular
└── manifest.json         # row counts + schema_version
```

Import is **additive** like Option B but extended to the content tail:
drafts / ideas / reflections / analytics UPSERT by their `id` field;
pillars / sources upsert by name / URL. Nothing is deleted just because
it's missing from the archive.

### Option D — copy the SQLite file

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
| **Dashboard** | Pipeline counts, what's up next, pillar mix, all-time engagement totals. **This week's signal** card runs the weekly brain reflection — Claude reads your last 7 days of analytics, voice samples, and discards, writes a paragraph on what's working, and drops 3 fresh ideas into the Ideas Bank tagged `auto-reflection`. **Memory snapshot** shows exactly what context the AI sees. |
| **Topics** | Pull headlines from RSS / Atom feeds (Hacker News and dev.to seeded by default). Feed autodiscovery means a regular blog URL like `https://dev.to/t/googlecloud` resolves to the underlying feed automatically. One click turns any topic into an angled idea in your voice, tagged `topic-intake` with the source URL preserved. |
| **Ideas** | Generate batches of ideas with Claude (hook + angle + format). Filter by pillar/status. Convert any idea into a draft in one click. Discarded ideas (and anything semantically similar) get blocked from re-pitching. |
| **Drafts** | Split-pane composer. Generate, rewrite ("tighter", "more contrarian"), score (Hook 1-10 / Voice 1-10), copy to clipboard, schedule. Winners feed back as positive examples on every future generation. |
| **Calendar** | Month grid of scheduled posts. **Auto-schedule** spreads ready drafts across weekdays at your preferred hours, balanced by pillar. |
| **Analytics** | Log impressions/likes/comments/follows per published post. Import LinkedIn's Creator Analytics xlsx export. Auto-matches rows to your drafts. **What's working?** gives a one-paragraph Claude analysis. |
| **Engagement** | Task list for comments + follow-ups. Comment generator writes 3 thoughtful comments for any post text you paste in. Comments now match your voice samples (the voice block is injected on every call). URL-only input is rejected with a clear error — Cadence can't fetch LinkedIn URLs. |
| **Voice** | Library of your past posts. Claude samples 3 at random for every generation, so the AI writes in *your* rhythm, not generic AI prose. |
| **Settings** | API key, **model picker** (Opus 4.5 / Sonnet 4.5 / Haiku 4.5 or pin a custom version; setting persists across restarts, top-bar pill shows what's live), creator profile, content pillars (with target % and color). Backup &amp; migrate offers three formats: **JSON** for full machine round-trips, **`profile.md`** for human-editable settings + pillars + voice + sources, **markdown `.zip`** for the whole DB with one file per draft (git-friendly). |

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
- **AI**: Anthropic SDK with Claude Sonnet 4.5 by default. Switch to
  Opus 4.5, Haiku 4.5, or pin a specific version from **Settings → AI
  backend → Model**. The picker writes to the `settings` table (wins
  over the `CLAUDE_MODEL` env var, which still works as a fallback for
  scripted setups). Prompt caching marks the static system block
  (`SYSTEM_BASE` + creator profile + voice samples + role instructions)
  as `cache_control: ephemeral` on every AI call that benefits from it
  (brain reflection, topic-to-idea, comment generator).
- **Dependencies**: `flask`, `anthropic`, `python-dotenv`, `openpyxl`,
  `feedparser`. Pure Python, no native code, no build step.
- **Frontend**: Vanilla JS, no build step
- **Tests**: `pytest` suite (59 tests across smoke, brain, topics,
  autodiscovery, engagement), runs in CI on Python 3.10 / 3.11 / 3.12

All AI prompts live in `app.py` so you can tune them. The `SYSTEM_BASE`
constant defines the writing rules (no em-dashes, banned filler words, etc.)
and is combined with your live voice samples on every call.

---

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full status.

**Recently shipped:**
- Weekly brain reflection with `cache_control: ephemeral` on the static
  system prompt and a one-button Dashboard card.
- RSS / Atom topic intake with HTML feed autodiscovery (paste a blog URL,
  Cadence finds the feed for you).
- Comment generator now injects voice samples on every call and rejects
  URL-only input with an actionable error.
- **Live model picker.** Switch between Opus 4.5, Sonnet 4.5, Haiku 4.5,
  or pin a specific version from Settings → AI backend. The DB-saved
  choice wins over the `CLAUDE_MODEL` env var; the top-bar pill shows
  which model is active per generation.
- **Human-editable backups.** `profile.md` round-trips your creator
  profile, content pillars, voice samples, and topic sources as plain
  markdown with YAML-style frontmatter. The markdown `.zip` archive
  extends that to the whole DB, with one file per draft so edits in any
  text editor become single-line diffs in git. Both imports are
  **additive** (UPSERT, never delete) so they're safe to re-run.

**Still planned:**
- Semantic memory via embeddings (so discarded patterns dedupe by meaning,
  not exact wording).
- Anthropic `web_search_20250305` integration alongside RSS for on-demand
  topic research.
- Reusable Claude skills package (`linkedin-hook`, `linkedin-rewrite`,
  `linkedin-score`, etc.) shippable separately from the Flask app.

## Contributing

PRs welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first — there are some
hard constraints (no build step, no new heavy deps without discussion).

For security issues, email hello@nomadicmehul.dev — see
[SECURITY.md](SECURITY.md).

---

## License

MIT. See [LICENSE](LICENSE).
