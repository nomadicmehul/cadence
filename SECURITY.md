# Security policy

## Threat model

This is a **single-user, local-first** tool. The intended deployment is
`http://127.0.0.1:5050` on the user's own machine. There is no auth, no
session, no CSRF token. **Do not expose it to the public internet.** If you
need remote access, put it behind a VPN or an SSH tunnel.

Sensitive material this app handles:

- **Anthropic API key** — stored in `data/pipeline.db` (SQLite, plaintext).
  Never sent to the frontend; the API only reports `api_key_set: true/false`.
- **Your unpublished drafts and analytics** — also in `data/pipeline.db`.
- **`.env`** — may contain `ANTHROPIC_API_KEY`. Already in `.gitignore`.

The DB lives at `data/pipeline.db`. Treat it the same way you'd treat your
password manager export.

## Reporting a vulnerability

If you find a security bug — credential leak, injection, sandbox escape,
anything that could harm a user — **do not open a public issue**. Email
mehul.patel@buildingminds.com with the details and we'll respond within
72 hours.

## What we already protect against

- **API key poisoning.** `is_valid_api_key()` rejects placeholder values
  like `sk-ant-...` so a bad `.env` won't waste 401s. The Claude Code CLI
  subprocess is invoked with `ANTHROPIC_*` env vars stripped so a bad
  parent-process key can't break the OAuth fallback.
- **SQL injection.** All user-supplied values go through SQLite parameter
  binding; no string-concatenated SQL.
- **Backup file API key leakage.** `python app.py export` and the
  `/api/backup/export` endpoint redact `anthropic_api_key` from the dump
  by default. Pass `--include-api-key` (CLI) or `?redact=0` (HTTP) only if
  you know what you're doing and the destination is trusted.

## What we deliberately do NOT do

- Store credentials in environment files we ship — `.env.example` is fully
  commented out so a copy-paste setup can't accidentally activate a
  placeholder credential.
- Add CSRF / session cookies — there's no remote authentication model that
  would make sense for a local single-user tool. Keep it on localhost.
