# CLAUDE.md

Context for Claude (or any AI agent) working in this repo. Read this first; it
will save you 30 minutes of file-spelunking and prevent re-introducing bugs we
already hit.

> **Project name: Cadence.** The local working directory is still
> `linkedin-growth/` for historical reasons; the GitHub repo and product
> name are both `cadence`. Don't rename the directory mid-session.

---

## Branch and commit conventions

These rules are load-bearing for this repo. Don't relax them without asking.

- **Branches start with `feature/`.** Every work branch in this repo is
  `feature/<short-kebab-topic>` (e.g. `feature/brain-loop`,
  `feature/semantic-memory`). Never commit to `main` directly. If you're on a
  `claude/<auto>` worktree branch from session-start, rename it before the
  first commit: `git branch -m feature/<topic>`.
- **No `Co-Authored-By: Claude` trailer.** Commits in this repo are authored
  by the human user only. Do not append the Claude / Anthropic co-author
  trailer that other repos sometimes use. The commit message body should
  read as if a human wrote it.
- **One commit per logical change.** Don't bundle unrelated edits into a
  single commit. The brain-loop work, a refactor, and a doc tweak are three
  commits.

## What this is

A self-hosted, single-user LinkedIn growth tool. **Open-source (MIT) as of
Phase 1.** Originally built for Mehul Patel (`@nomadicmehul` — DevOps
Evangelist, AWS Community Builder, Auth0 Ambassador, founder of CloudCaptain,
currently at BuildingMinds), now generalised so any creator can onboard in
60 seconds via the first-run modal. The project owner / primary user is
still Mehul; defer to existing patterns (tone, banned-words, format guides)
unless explicitly redirected.

The mental model is a content pipeline:

```
Ideas → Drafts → Scheduled → Published → Analytics → (feedback loop) → smarter Ideas
```

Powered by Claude. Runs locally on the user's Mac. Data never leaves the
machine except prompts to the Claude API. Manual copy-paste publishing (no
LinkedIn API; LinkedIn doesn't expose personal post analytics, see "Why no
LinkedIn API" below).

---

## Stack

- **Backend**: Python 3.10+, Flask, SQLite. Single file `app.py` (~2000 lines).
- **AI**: Anthropic SDK *or* the local `claude` CLI as fallback (auto-detected).
- **Frontend**: vanilla JS + HTML + CSS. No build step. One template
  (`templates/index.html`), one stylesheet, one JS file.
- **Excel parsing**: openpyxl for LinkedIn analytics import.
- **Tests**: `pytest` smoke suite under `tests/`, runs in GitHub Actions CI on
  Python 3.10 / 3.11 / 3.12. Mocks all Claude calls.
- **Process management**: `run.sh` creates `.venv`, installs deps, starts the
  server. The user has hand-edited this; don't revert without asking.

There is intentionally no React/Vue/build pipeline. Adding one would be a
regression — keep dependencies minimal.

---

## File map

```
linkedin-growth/
├── app.py                  # All Flask routes, DB schema + migrations, AI helpers, parsers, CLI
├── requirements.txt        # flask, anthropic, python-dotenv, openpyxl
├── run.sh                  # Bootstrap script (user has tweaked it; preserve)
├── .env.example            # Fully commented — see "Env poisoning" below
├── .gitignore
├── README.md               # User-facing setup + feature tour + migration guide
├── CLAUDE.md               # This file
├── CONTRIBUTING.md         # PR rules — no build step, no new heavy deps
├── SECURITY.md             # Threat model + key-handling rules
├── CODE_OF_CONDUCT.md      # Contributor Covenant 2.1
├── LICENSE                 # MIT
├── .github/
│   ├── workflows/test.yml      # CI — pytest on 3.10/3.11/3.12
│   ├── ISSUE_TEMPLATE/         # bug + feature templates
│   └── PULL_REQUEST_TEMPLATE.md
├── tests/
│   ├── conftest.py             # tmp-DB fixtures + monkeypatched ANTHROPIC_API_KEY
│   └── test_smoke.py           # endpoint contracts + backup roundtrip + first-run state
├── data/
│   └── pipeline.db             # SQLite, created on first run, NEVER ship in repo
├── templates/
│   └── index.html              # Single page; tab-based SPA
└── static/
    ├── style.css
    └── app.js                  # Frontend logic — fetches /api/*, renders tabs, onboarding
```

---

## How to run

```bash
./run.sh
```

Opens at `http://127.0.0.1:5050`. The user is on macOS; paths use
`~/linkedin-growth/`.

For programmatic testing without a server, use Flask's test client:

```python
import app
client = app.app.test_client()
client.get("/api/dashboard").get_json()
```

This avoids subprocess flakiness in CI/sandbox environments.

---

## Auth model — read this carefully, it has surprised us

Two backends, auto-detected in this priority order:

1. **Anthropic API key** — from `ANTHROPIC_API_KEY` env var or saved in DB
   (table `settings`, key `anthropic_api_key`).
2. **Claude Code CLI** — `claude` binary on PATH, using OAuth session from
   `claude login`.

Two non-obvious rules:

### `is_valid_api_key()` validation

A key counts as valid only if: starts with `sk-ant-`, length ≥ 30, contains no
`...`, doesn't end with `-here` or `-key`. This rejects the placeholder
`sk-ant-...` that python-dotenv would otherwise load from a poisoned `.env`.

### CLI subprocess gets a scrubbed env

When invoking the `claude` CLI we strip *all* `ANTHROPIC_*` env vars before
the call. Claude Code prefers an env-var key over its OAuth session; if the
parent has a bad key, the CLI fails too. Scrubbing forces it to fall back to
the OAuth session. **Never remove this.** See `_call_via_cli` in `app.py`.

### Auto-fallback in `call_claude`

If the API call errors out (e.g., 401), and CLI is available, we transparently
retry via CLI. The test endpoint `/api/auth/test` reports which backend
actually answered.

### Model resolution — DB beats env (opposite of API key resolution!)

`get_model()` resolves the model for the next API call in this priority:

1. Per-call argument (`call_claude(system, user, model="claude-opus-4-5")`)
2. **DB setting** (`settings.claude_model`, written by the UI picker)
3. `CLAUDE_MODEL` env var (legacy / CI / scripted setups)
4. Built-in default (`BUILTIN_DEFAULT_MODEL = "claude-sonnet-4-5"`)

This is intentionally **opposite** of the API key resolution (env beats DB
there). Reasoning: the API key is a credential whose source matters for
security audits; the model is a preference whose value matters for the
user's UX. UI selection is the supported sticky path.

`is_valid_model()` is a cheap sanity gate (starts with `claude-`, no
whitespace, reasonable length). It rejects placeholders so a typo in
either source doesn't silently break the next AI call. The Settings PUT
endpoint also validates and returns 400 with a helpful message.

The CLI backend ignores all of this — the `claude` CLI uses whatever
model it's configured with. The UI dropdown disables itself when CLI is
active, and `auth_status()` returns `active_model: ""` on CLI mode.

---

## AI generation rules

All prompts use `SYSTEM_BASE` + `creator_block()` + (optionally) `voice_block()`
+ memory blocks. Hard rules in `SYSTEM_BASE`:

- **No em-dashes.** Use periods or line breaks.
- **Banned words**: delve, leverage, unlock, unleash, game-changer.
- **Banned openings**: "In today's fast-paced world" and equivalents.
- **No hashtags** unless explicitly requested. Max 3, lowercase, if used.
- First line stops the scroll. Every line is a deliberate beat.

Voice samples — 3 random ones from `voice_samples` table — are injected on
every draft generation. Top performers (see Memory loop) are injected on every
idea + draft generation.

### Format guides

`FORMAT_GUIDES` constant maps `{story, list, contrarian, tutorial, carousel,
bts}` to structure prompts. Don't add new formats without updating the dropdown
in `index.html` (line ~158, `<select id="ed-format">`) too.

---

## Brain loop (weekly reflection)

`POST /api/brain/reflect` and `python app.py reflect` both call
`run_reflection(window_days=N)`. The function:

1. Pulls last N days of published-post analytics, recently discarded ideas,
   the previous reflection's summary, and active pillars.
2. Sends a two-block system prompt: a static block (`SYSTEM_BASE +
   creator_block + voice_block + coach instructions`) marked with
   `cache_control: ephemeral` so the API can cache it, and a variable user
   block with the actual data.
3. Asks Claude for JSON with `summary`, `signals` (best pillar/format,
   weakest pillar, topics to double down), and `next_ideas` (3 fresh ones).
4. Inserts the 3 ideas into the `ideas` table with `source='auto-reflection'`
   and the matched pillar (by case-insensitive name lookup) so they appear in
   the Ideas Bank tagged accordingly.
5. Writes the row to `reflections`.

The Dashboard "This week's signal" card renders the latest reflection.
Triggered manually for now — no in-process cron. For automation, wire
`python app.py reflect` into macOS launchd or any other scheduler.

The CLI backend (`claude` binary) doesn't support prompt caching; the
`_system_blocks_to_str` helper flattens the structured system prompt back to
a string before invoking the CLI. Cache savings apply only on API mode.

## Topic intake loop (RSS / Atom)

Built so the user doesn't have to be the only source of ideas. Configured
feeds (HN, dev.to, vendor blogs) are fetched on demand by `fetch_topics()`,
URL-deduped, and inserted into the `topics` table. Each topic has a "Draft
an angle" button → `POST /api/topics/{id}/draft` → Claude reads the
topic + pillars + voice and writes an angled idea into the `ideas` table
tagged `source='topic-intake'`. The topic row is then marked `status='used'`
with a link back to the idea.

Safety knobs in `app.py`:
- `TOPIC_FETCH_TIMEOUT_SEC = 10` — per-source HTTP timeout.
- `TOPIC_FETCH_MAX_BYTES = 2 * 1024 * 1024` — hard byte cap per response.
- `TOPIC_FETCH_MAX_ITEMS_PER_SOURCE = 30` — don't drown the table.
- Per-source try/except: one dead feed never aborts the batch.

`_http_get_bounded()` and `_parse_feed_entries()` are the seams to
monkeypatch in tests — never hit real network from CI. See
`tests/test_topics.py` for the canned-RSS pattern.

Adding new feed kinds (e.g. JSON Feed, Anthropic web search):
- New `kind` value on `topic_sources` (no migration needed, just a string).
- A parser function alongside `_parse_feed_entries` that returns the same
  `{external_id, url, title, summary, published_at}` dict shape.
- Dispatch in `fetch_topics()` based on `src["kind"]`.

## Memory feedback loop (the killer feature)

Three context blocks injected into AI prompts:

| Block | What it does | Where used |
|-------|-------------|------------|
| `voice_block()` | 3 random past posts you marked as your voice | draft generation |
| `winners_block(pillar_id, limit)` | Top published posts by `likes + 2*comments`, optionally restricted to a pillar | idea generation, draft generation |
| `discarded_block(limit)` | Recent ideas the user marked discarded | idea generation |

The Dashboard "Memory snapshot" card (frontend `loadMemorySnapshot()`) shows
the user exactly what the AI is seeing. Each top performer has a "Repurpose"
button → `/api/drafts/{id}/repurpose` → generates 3 fresh format variants.

When extending memory, add the new block to `winners_block` style helpers and
inject in the appropriate generation endpoint. **Don't bypass `voice_block`** —
voice consistency is non-negotiable.

---

## Database schema

Defined in `SCHEMA` constant in `app.py`. Tables:

- `schema_version` — applied migration versions; populated by `init_db()`
- `settings` (key/value) — `anthropic_api_key`, `creator_name`,
  `creator_bio`, `target_audience`, `weekly_target`, `preferred_hours`,
  `default_format`
- `pillars` — content pillars with target_pct, color, sort_order
- `ideas` — pillar_id, title, hook, angle, source, status (raw / drafted /
  discarded)
- `drafts` — idea_id, pillar_id, title, body, format, hook_score, voice_score,
  score_notes, status (draft / ready / scheduled / published), scheduled_for,
  posted_at
- `analytics` — draft_id, impressions, likes, comments, reposts, follows,
  profile_visits, recorded_at
- `voice_samples` — content, label
- `engagement_tasks` — draft_id, type (comment / follow_up / respond),
  details, due_date, completed
- `reflections` — weekly brain loop output. window_days, summary,
  signals_json (best/weakest pillar, best format, topics), ideas_created_json
  (list of idea ids dropped into the pipeline by that reflection).
- `topic_sources` — RSS / Atom feed configs: name, url (UNIQUE), kind,
  enabled, last_fetched_at, last_status.
- `topics` — ingested headlines: source_id, external_id, url (UNIQUE),
  title, summary, published_at, status (new / queued / used / dismissed),
  pillar_id (auto-tagged on draft), idea_id (link back when used).

### Migrations (added in Phase 1)

There's a `MIGRATIONS = [(version, fn), ...]` list in `app.py`. `init_db()`
runs every migration whose version isn't yet in `schema_version`, then records
it. Each migration function takes a `sqlite3.Connection` and must be
idempotent.

To add a column or table:

1. Add it to `SCHEMA` so fresh installs get it directly.
2. Write `_migration_vN(conn)` that runs the equivalent `ALTER TABLE` on
   existing DBs, guarded by `PRAGMA table_info` checks so re-running is safe.
3. Append `(N, _migration_vN)` to `MIGRATIONS`.
4. Bump `CURRENT_SCHEMA_VERSION = N`.
5. Test against a populated DB (use one of your own backups via
   `python app.py import`).

**Never** edit an existing migration after it's been released — write a new one.

### Backup / migrate (added in Phase 1)

Three surfaces, same `export_to_dict` / `import_from_dict` core:

- **CLI**: `python app.py export backup.json` / `python app.py import backup.json`
- **HTTP**: `GET /api/backup/export` (downloads JSON), `POST /api/backup/import`
- **UI**: Settings → Backup & migrate

The export redacts `anthropic_api_key` by default. Pass `--include-api-key`
(CLI) or `?redact=0` (HTTP) only when moving to a trusted machine.

Import refuses backups whose `schema_version` is newer than the running app —
update the app first.

The user has real data — never delete `data/pipeline.db`. If you need a clean
slate for testing, use the `tests/conftest.py` fixture pattern (per-test
temp DB).

### profile.md (human-editable export/import)

Companion to the JSON backup, but readable in any markdown editor and
friendly to git diffs. Contains: creator profile settings (name, handle,
bio, target_audience, weekly_target, preferred_hours, default_format),
content pillars, voice samples, and topic sources. Deliberately
**excludes** the API key (credential — stays redacted, like the JSON
backup) and the content tail (ideas, drafts, analytics, reflections,
topics — those live in JSON backup only).

Three surfaces, same `_profile_to_markdown` / `_parse_profile_markdown` /
`_apply_profile_dict` core:

- **CLI**: `python app.py profile export profile.md` / `profile import profile.md`
- **HTTP**: `GET /api/profile/export` / `POST /api/profile/import {markdown: "..."}`
- **UI**: Settings → Creator profile → **Save to profile.md** / **Load from file**

Format: YAML-style frontmatter for short scalars, `##` H2 sections for
prose (Bio, Target audience), `##` H2 + `###` H3 sub-items with
bulleted metadata + body for list types (Pillars, Voice samples,
Topic sources).

**Import semantics — additive, never destructive.** This is load-bearing
and a future agent should NOT "simplify" it to a clean-slate replace:

- settings: UPDATE keys present in the file; leave others
- pillars: UPSERT BY NAME; pillars in DB but not in the file are left
  alone (preserves foreign-key references from drafts / ideas / topics
  via ON DELETE SET NULL)
- voice: APPEND samples whose content isn't already in DB; re-importing
  the same file is a no-op
- topic sources: UPSERT BY URL; sources in DB but not in the file are
  left alone (topics.source_id is ON DELETE CASCADE, so deleting a
  source would wipe its ingested headlines)

To wipe-and-replace, use the JSON backup with `mode=replace`.

Empty-section placeholders (`_(empty)_`, `_(no description)_`, etc.) are
recognised on parse and treated as empty strings — they never overwrite
existing values with the literal placeholder text.

### Markdown backup .zip (full archive)

Extends the profile.md idea to the whole DB. A `.zip` containing
`profile.md`, `drafts/NNNN-slug.md` (one file per draft), `ideas.md`,
`reflections.md`, `topics.md`, `analytics.csv`, and a `manifest.json`
with row counts and `schema_version`. Companion to the JSON backup;
human-readable and git-friendly, but never the canonical source of
truth (that's still `data/pipeline.db`).

Three surfaces:
- **CLI**: `python app.py backup export-md backup.zip` / `backup import-md backup.zip`
- **HTTP**: `GET /api/backup/export-markdown` / `POST /api/backup/import-markdown` (body: `{zip_base64: "..."}`)
- **UI**: Settings → Backup & migrate → **Download backup (.zip)** / **Restore from .zip**

Identity for round-trip:
- drafts / ideas / reflections / analytics: **UPSERT BY id** (frontmatter
  `id:` field for the .md files, CSV `id` column for analytics). Editing a
  file and re-importing UPDATES the row, doesn't create a duplicate.
- pillars / topic_sources: same name / url upsert as profile.md.
- voice samples: same content-hash dedup as profile.md.

**Import is additive, never destructive.** Re-importing an archive after
adding new rows to the DB does NOT delete those new rows. To wipe and
replace, use the JSON backup with `mode=replace`.

Draft body safety: each draft .md uses frontmatter for all metadata,
then reads body verbatim to end-of-file. Markdown headings INSIDE a
draft body (`## Step 1` in a tutorial post) never confuse the parser
because we don't section-split the body. See
`tests/test_backup_markdown.py::test_draft_with_markdown_headings_in_body_roundtrips`.

Analytics is CSV not markdown — tabular numeric data doesn't markdown
well. The CSV columns match the `analytics` table 1:1, including the
`id` column which carries the UPSERT identity.

The `manifest.json` carries `schema_version`. Imports refuse archives
from a newer schema than the running app.

---

## CSV / XLSX import (the trickiest code in the repo)

LinkedIn's personal Creator Analytics export is an `.xlsx` workbook with
sheets like Top posts, Discovery, Engagement, Followers, Demographics. Older
exports were CSV. Importer handles both.

### Pipeline

1. Frontend reads file, base64-encodes if xlsx, POSTs to
   `/api/analytics/import-preview`.
2. `_xlsx_read_all_sheets()` reads every sheet, scores each by post-keyword
   density + name bonuses (post/top +50, follower/demographic -5) - empty
   penalty (-30). Returns sorted best-first.
3. Auto-pick = highest-scoring sheet. User can override via
   `sheet_override` parameter or the UI dropdown.
4. Header detection scans for any of HEADER_KEYWORDS. Falls back to first
   multi-column row if no keyword match.
5. Column auto-detection via `find_col()` — fuzzy substring match.
6. Two-pass row matching: pass 1 = body-snippet overlap (high confidence),
   pass 2 = date-proximity (within ±3 days), each draft claimed at most once.
7. Frontend shows preview table; user confirms; commit endpoint inserts
   analytics rows + marks drafts published.

### Critical gotcha: openpyxl dimension tag bug

LinkedIn writes a wrong `<dimension>` tag (often `A1:A1`). openpyxl in
**`read_only=True`** mode trusts that tag and only sees the top-left cell —
every sheet appears to have 1 row. **Don't use `read_only=True`.** Iterate
explicitly via `ws.cell(row, column)` over `ws.max_row × ws.max_column`. See
`_xlsx_read_all_sheets()`.

### Column keyword sets

Add new column variants here when LinkedIn changes export format:

```python
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
```

---

## Bugs we hit and fixed — preserve this institutional memory

### 1. Modal always visible (CSS specificity)

`.modal-backdrop { display: grid }` overrode the HTML `[hidden]` attribute,
making the modal permanently visible with empty content. Fix in `style.css`:

```css
.modal-backdrop[hidden] { display: none !important; }
```

Don't remove this rule.

### 2. Env poisoning — the .env.example trap

Original `.env.example` shipped with `ANTHROPIC_API_KEY=sk-ant-...` (literal
placeholder). `run.sh` copies `.env.example` → `.env` on first run.
python-dotenv loaded the placeholder string into the Python process, which:

- The Anthropic SDK then sent to the API → 401 invalid x-api-key.
- The CLI subprocess inherited → CLI also failed with the same error.

Two fixes, both already in place:

1. `.env.example` now ships fully commented out.
2. `is_valid_api_key()` rejects placeholders.
3. `_call_via_cli` strips ANTHROPIC_* env vars before subprocess.

If you re-introduce a default uncommented `ANTHROPIC_API_KEY=...` in
`.env.example`, you will resurrect this bug.

### 3. Pip missing in fresh venv

Some macOS Python installs ship venvs without pip. Original `run.sh` failed.
Current `run.sh` uses `python -m pip` and bootstraps via `ensurepip --upgrade`.
Don't revert to bare `pip`.

### 4. Auto-schedule date-matching same draft twice

CSV import originally had a bug where date-fallback could match the same draft
to multiple CSV rows. Two-pass matcher with a `claimed` set fixes it. Never
remove the claimed-set check.

---

## Testing patterns

The user-side environment (sandboxed Linux in some setups) has SQLite I/O
quirks for the bind-mount. Tests work cleanly in `/tmp`. Pattern:

```bash
cd /tmp && rm -rf scratch && cp -r /path/to/linkedin-growth /tmp/scratch && cd /tmp/scratch
rm -f data/pipeline.db
python3 -c "
import sys, os
os.environ.pop('ANTHROPIC_API_KEY', None)  # ensure clean state
sys.path.insert(0, '/tmp/scratch')
import app
client = app.app.test_client()
# ... use client.get / client.post / client.put
"
```

Mock the AI calls when CLI is detected by overriding
`app.subprocess.run` and `app.shutil.which`. See the smoke tests we ran in
conversation history for the pattern.

For Anthropic SDK calls, set a fake key and let the SDK 401 — the auto-fallback
test gives us "API failed → try CLI" coverage in one shot.

---

## What NOT to do

- **Don't add a build step / framework.** Vanilla JS is the constraint. The
  user runs this locally on a Mac and shouldn't need npm.
- **Don't introduce LinkedIn scraping or browser automation.** It's against
  LinkedIn's ToS (Section 8.2) and the user's account is the most expensive
  asset here.
- **Don't store API keys in plaintext anywhere except SQLite.** Frontend
  receives only `api_key_set: bool`.
- **Don't bypass `is_valid_api_key()`.** It's the only thing standing between
  us and a re-poisoning incident.
- **Don't use openpyxl `read_only=True`** for LinkedIn xlsx imports. See
  the dimension-tag bug above.
- **Don't delete `data/pipeline.db`.** It has the user's real ideas, drafts,
  voice samples, and analytics history.
- **Don't modify `run.sh` without checking with the user.** They've hand-edited
  it.
- **Don't add hashtags or em-dashes** in any AI-generated content. The
  banned-words rules in `SYSTEM_BASE` exist because LinkedIn is allergic to
  AI-flavored writing.

---

## Why no LinkedIn API

Personal post analytics are not exposed by any LinkedIn API:

- Marketing Developer Platform / Reporting API: company pages + ad accounts
  only, partner approval required (slow, often denied).
- `r_member_social` scope: gives you post text, not impressions/likes/views.
- "Sign in with LinkedIn": basic profile only.

The supported path is the manual xlsx export from Creator Analytics, which is
why the importer exists. Don't promise the user a real-time API integration —
LinkedIn doesn't have one for personal posts and won't.

---

## Open follow-ons (not built yet)

If the user asks for these, here's where to start:

- **Auto-promote winners to voice samples.** When a published post crosses an
  engagement threshold, copy its body into `voice_samples`. ~10 lines, hooks
  into `api_analytics_create`.
- **Cross-pillar pattern learning.** Modify `winners_block` to optionally pull
  global top performers (any pillar) when generating ideas, with a flag for
  "stay on niche" vs "borrow energy from other pillars".
- **Embedding-based dedup.** Currently "avoid recent ideas" is exact-string;
  semantic similarity would catch "moving off Kubernetes" matching "we killed
  K8s." Use Anthropic embeddings or a local model.
- **A/B hook test runner.** Generate 3 hooks for one body, log which CTR'd
  best, feed that pattern back.
- **Comment harvesting.** When the user logs analytics, optionally let them
  paste the comments thread; mine it for follow-up ideas.
- **Weekly digest scheduled task.** Add a `schedule` skill task that runs
  `/api/analytics/insights` every Monday and emails/posts the result.

---

## Personalization (rewritten in Phase 1)

The tool is now generic enough that anyone can use it. Default seed data
lives in constants at the top of `app.py`:

- `DEFAULT_PILLARS` — five generic starter pillars (Industry insights,
  Tactical tutorials, Personal stories, Tools and workflows, Behind the
  scenes). The user re-labels these in the onboarding modal or Settings.
- `DEFAULT_VOICE_SAMPLES` — `[]`. The onboarding modal asks new users to
  paste 3 of their best past posts so Claude has a real voice to imitate.
- `DEFAULT_SETTINGS` — empty `creator_name`, `creator_handle`,
  `creator_bio`, `target_audience`. Filled in via the onboarding modal.

### First-run detection

`/api/onboarding/status` returns `{first_run: true}` when `creator_name` is
empty. The frontend boot block (`app.js` bottom) calls it and pops
`openOnboarding()` if true. Posting to `/api/onboarding/complete` writes
profile fields and seeds voice samples in one call.

**Mehul's existing DB is untouched** — the seed-on-first-run logic only fires
when each table is empty (`SELECT COUNT(*) == 0`), so changing the constants
doesn't overwrite a populated DB.

---

## Quick reference: key endpoints

```
GET  /                              # SPA
GET  /api/dashboard                 # counts, up next, pillar mix, totals
GET  /api/memory                    # memory snapshot for Dashboard card
GET  /api/auth/status               # which backend is active
POST /api/auth/test                 # ping: does any backend actually work?
POST /api/settings/clear-api-key    # remove the saved key (dirty-key recovery)

GET  /api/onboarding/status         # {first_run, has_pillars, has_voice_samples}
POST /api/onboarding/complete       # write profile + seed voice samples in one call

POST /api/brain/reflect             # weekly reflection: summary + 3 auto-ideas (body: {window_days})
GET  /api/brain/reflections         # list past reflections (?limit=10)

GET/POST          /api/topics/sources       # CRUD on RSS / Atom feed configs
PUT/DELETE        /api/topics/sources/{id}
POST              /api/topics/fetch         # pull all enabled (or {source_ids: [...]}), dedup by URL
GET               /api/topics               # list (?status=, ?source_id=, ?limit=)
PUT/DELETE        /api/topics/{id}          # status change / remove
POST              /api/topics/{id}/draft    # Claude turns the topic into an angled idea

GET  /api/backup/export             # download full DB as JSON (?redact=0 keeps API key)
POST /api/backup/import             # body {payload, mode: 'replace'|'merge'}

GET  /api/profile/export            # download creator profile as profile.md
POST /api/profile/import            # body {markdown: "..."} — additive, never deletes

GET  /api/backup/export-markdown    # download full DB as .zip of markdown files
POST /api/backup/import-markdown    # body {zip_base64: "..."} — additive UPSERT BY ID

GET/POST/PUT/DELETE /api/pillars
GET/POST/PUT/DELETE /api/ideas
POST /api/ideas/generate            # AI batch idea gen (Claude)

GET/POST/PUT/DELETE /api/drafts
POST /api/drafts/generate           # AI draft from idea or brief
POST /api/drafts/{id}/rewrite       # AI rewrite with instruction
POST /api/drafts/{id}/score         # AI hook + voice scoring
POST /api/drafts/{id}/repurpose     # AI: 3 fresh format variants

GET  /api/calendar                  # scheduled drafts in date range
POST /api/calendar/auto-schedule    # spread ready drafts across days

GET/POST /api/analytics
GET  /api/analytics/insights        # AI: "what's working?"
POST /api/analytics/import-preview  # CSV/XLSX parse + auto-match
POST /api/analytics/import-commit   # confirm + insert

GET/POST/PUT/DELETE /api/engagement
POST /api/engagement/comments       # AI: 3 comment templates for a target post

GET/POST/DELETE /api/voice
```

When adding a route, also add it to this list. When removing, remove it
here too. This is the API contract.
