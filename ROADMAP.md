# Roadmap

Where Cadence is going. Phases are sequenced so each one stays useful even
if the next never ships.

Status legend:
- ✓ **Shipped** — in `main`, covered by tests
- 🚧 **In progress** — design agreed, code being written
- 💭 **Proposed** — design sketched, awaiting agreement
- ❌ **Out of scope** — explicitly not happening; here so contributors
  don't accidentally try

---

## Phase 1 — Open-source readiness ✓ Shipped

The minimum viable "anyone can clone this and use it" pass.

| | What |
|---|---|
| ✓ | Generic seed pillars and empty creator profile (was hardcoded for Mehul) |
| ✓ | First-run onboarding modal that captures name, bio, audience, and 3 voice samples in one screen |
| ✓ | Schema migration framework (`schema_version` table + idempotent `MIGRATIONS` list) |
| ✓ | JSON backup / restore via UI, HTTP, and CLI — moves your data between machines in 60 seconds |
| ✓ | API key redacted from backups by default; `--include-api-key` opt-in for trusted destinations |
| ✓ | `pytest` smoke suite (12 tests) wired into GitHub Actions CI on Python 3.10 / 3.11 / 3.12 |
| ✓ | LICENSE (MIT), CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, issue + PR templates |
| ✓ | Renamed product from "LinkedIn Growth Tool" to **Cadence** |

**Outcome:** A new contributor can clone, run `./run.sh`, and have a working
local instance with their own voice in five minutes.

---

## Phase 2 — Brain (tighter feedback loop) 💭 Proposed

Make the tool smarter at remembering what worked and what didn't.

### 2.1 Semantic memory

The current memory blocks are flat string matching:
- `discarded_block()` lists exact ideas the user rejected
- `winners_block()` pulls top performers by raw engagement score

Both miss semantic similarity. "Moving off Kubernetes" doesn't match "we
killed K8s" — so the AI re-pitches the same idea with different words.

**Plan:**
- Add `post_embeddings` table: `(id, kind, ref_id, vector_blob, created_at)`
- On insert/update of any draft, voice sample, or discarded idea, embed it
  (provider TBD — `voyage-3-lite` API or local `sentence-transformers/all-MiniLM-L6-v2`)
- New helper `find_similar(text, kind, limit)` returns cosine-sim top-k
- Use it in: `discarded_block()` (semantic dedup), `winners_block()` (find
  past winners similar to the current idea), Drafts composer (live "this is
  like winners X and Y" badge)

**Open question for the user:** local model (free, 80MB download, slower
first call) vs API (cheap, fast, but adds a vendor)?

### 2.2 Daily reflection task

A `/api/brain/reflect` endpoint that runs on a schedule:
- Reads last 7 days of analytics, voice samples, discarded ideas
- Asks Claude: "what pattern is working, what's getting ignored, what should
  this person try next week?"
- Writes one paragraph to a `reflections` table
- Drops 3 fresh ideas into `ideas` tagged `auto-reflection`

Triggered via the `schedule` skill (cron-style) so it runs even when the app
isn't open.

### 2.3 Auto-promote winners → voice library

Already in the original roadmap. ~10 lines:
- When `analytics_create` records a post crossing a threshold (e.g.
  likes + 2*comments > P75 of all published posts), copy `drafts.body`
  into `voice_samples` with label `auto-winner`.
- User can prune in Voice tab.

---

## Phase 3 — Topic search ("what should I post about?") 💭 Proposed

The current pipeline assumes you bring the idea. This phase makes Cadence
suggest fresh angles based on what's happening *outside* your existing voice.

Three options, in order of effort:

### 3.a Web search via Anthropic's tool

`POST /api/search?q=...&pillar=...` calls Claude with the
`web_search_20250305` tool, returns 3-5 angled hooks per pillar from the
results. ~1 day of work. Costs per search.

### 3.b RSS / HN ingest

Configurable feed list (HN front page, AWS / Auth0 / Anthropic blogs,
dev.to tagged feeds, your competitors' RSS). Pulls every hour into a `topics`
table. The "search" UI is just filter + "draft an angle for this." Free, no
rate limits, you control the firehose.

### 3.c Both (recommended)

RSS for steady stream + on-demand web search for "go deep on X right now."
Same `topics` table, two ingestion paths.

**Out of scope for this phase:** social-media scraping (Twitter/X, LinkedIn
itself). LinkedIn's ToS forbids scraping their own surface, and Twitter's
API is now paid-tier-only.

---

## Phase 4 — Reusable Claude skills 💭 Proposed

So the *value* of Cadence's prompts isn't locked inside this Flask app.

Ship a `.claude/skills/` directory with self-contained markdown files that
any Claude Code user can drop into `~/.claude/skills/`:

| Skill | What it does |
|---|---|
| `linkedin-hook` | Turn a rough idea into 3 scroll-stopping hooks following the banned-words rules |
| `linkedin-rewrite` | Tightens a draft. Removes em-dashes, banned filler, AI-tells |
| `linkedin-score` | Rates Hook 1-10 + Voice match 1-10 with notes |
| `linkedin-repurpose` | Same body, 3 different formats (story/list/contrarian) |
| `linkedin-comment` | 3 thoughtful comments for a post you paste in |

Each is a 30-line markdown file with frontmatter. Distributing them this way
means people who never run the Flask app still get value, which is the
highest-leverage piece for OSS impact.

**Optional next step:** package as a Claude Code plugin (single `gh repo` you
add to your plugin marketplace). The plugin author docs are at
docs.claude.com/en/docs/claude-code/plugins.

---

## Out of scope (deliberately) ❌

These come up regularly and the answer is no — for documented reasons.

| | Why not |
|---|---|
| **LinkedIn API integration for personal post analytics** | LinkedIn doesn't expose this. Marketing Developer Platform is for company pages + ad accounts only. The xlsx import is the only real path. |
| **Browser automation / scraping LinkedIn** | Against ToS section 8.2. The user's account is the most expensive asset; we won't risk it. |
| **A build step / framework (React, Vue, Tailwind, bundler)** | The whole point is `./run.sh` working on a fresh Mac in 30 seconds. Adding npm would be a regression. |
| **Multi-user / team mode** | Threat model is single-user localhost (see SECURITY.md). Multi-user means auth, which means session, which means CSRF, which means a real deployment story. None of that is in scope. |
| **Hosted SaaS version** | Same reason. Cadence is local-clone-only. No PyPI, npm, Docker Hub, or Homebrew. |
| **Real-time collaboration** | See above. |
| **Mobile app** | Not happening. The desktop browser at `127.0.0.1:5050` is mobile-friendly enough if you SSH-tunnel from your phone. |

---

## How phases get picked up

The user (Mehul, project owner) decides which phase to start. Each phase is
designed to be self-contained — you can ship Phase 2 without Phase 3, etc.

Contributors: open an issue on the phase you'd like to tackle so we can
align on design before code lands. PRs that bundle multiple phases will
likely get split.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the PR rules and
[CLAUDE.md](CLAUDE.md) for implementation context.
