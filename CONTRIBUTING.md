# Contributing

Thanks for considering a contribution. This is a small, opinionated codebase
and we'd like to keep it that way. Read this before sending a PR — it'll save
both of us time.

## Ground rules

- **No build step.** Vanilla JS, vanilla CSS, no React/Vue/Tailwind/bundler.
  The whole point is `./run.sh` working on a fresh Mac in 30 seconds.
- **Single file backend.** `app.py` is intentionally monolithic. Don't split
  it into a package unless the file crosses ~3000 lines.
- **No new heavy dependencies** without discussion. The current set is
  Flask + Anthropic + python-dotenv + openpyxl. That's the whole tree.
- **Don't break local-first.** No telemetry, no cloud calls except to the
  Claude API the user explicitly configured.

## Setup

```bash
git clone https://github.com/nomadicmehul/cadence.git
cd cadence
./run.sh        # creates .venv, installs deps, starts the server
```

You'll need either an Anthropic API key or the Claude Code CLI installed
(`claude login`). Either works.

## Running tests

```bash
.venv/bin/python -m pytest tests/ -v
```

The smoke tests use Flask's test client and a temporary SQLite file. They
mock out Claude calls so nothing hits the network. CI runs the same suite
on every PR.

## Pull request checklist

Before opening a PR:

- [ ] Tests pass (`pytest tests/ -v`)
- [ ] You've manually tested the affected tab in a browser
- [ ] No new top-level dependencies (or you've justified them in the PR)
- [ ] No em dashes or banned filler words in any AI prompt strings (the
      `SYSTEM_BASE` rules apply to prompts the same way they apply to output)
- [ ] If you touched `app.py` schema: added a migration in `MIGRATIONS`
      rather than editing `SCHEMA` in place
- [ ] If you added a new API route: documented it in `CLAUDE.md` under
      "Quick reference: key endpoints"

## Schema changes

The DB has migrations now. To change schema:

1. Add the new column / table directly into `SCHEMA` (so fresh installs get it).
2. Add a migration function `_migration_vN(conn)` that runs the equivalent
   `ALTER TABLE` for existing databases, guarded by `PRAGMA table_info`.
3. Append `(N, _migration_vN)` to the `MIGRATIONS` list.
4. Bump `CURRENT_SCHEMA_VERSION = N`.
5. Test against an existing populated DB (use one of your own backups).

## Reporting bugs

Use the GitHub issue tracker. Include:

- What you ran, what you expected, what happened
- Output of `./run.sh` (or stack trace)
- Whether you're using API key or CLI auth
- macOS/Linux/Windows + Python version

For analytics-import bugs specifically, attach the xlsx (with sensitive rows
removed) — the parser's column detection is the most fragile part of the
codebase and we need real samples.

## Code of Conduct

By participating, you agree to abide by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
