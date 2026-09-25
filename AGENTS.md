# The Great Logout: agent guide

## Scope

These instructions apply to the complete repository. Preserve unrelated user
changes and run `git status --short` before editing.

## Project

The Great Logout is a bilingual public campaign for a visible, conscious exit
from addictive social platforms. The site provides background material, a post
generator, and an email guide. Keep the tone clear, human, encouraging, and
structurally critical without sounding bureaucratic or promotional.

## Production architecture

- Nginx serves the static site from `/home/deploy/apps/thegreatlogout.org`.
- `thegreatlogout-guide.service` runs the FastAPI guide API on `127.0.0.1:8788`.
- `thegreatlogout-send-due.timer` starts the due-email job every 15 minutes.
- Guide subscribers and send state live in `data/thegreatlogout.db`.
- Consent-based first-party analytics are proxied to the NDS backend on
  `127.0.0.1:8060` and shown in `admin.netzldatasolutions.at`.
- Postmark is the only external transactional-email service.
- DNS is hosted at INWX. Cloudflare and GitHub Pages are no longer in the live
  request path; legacy material remains temporarily for rollback.

## Main paths

- English site: root-level HTML files.
- German site: `de/`.
- Shared campaign styles and scripts: `assets/`.
- German-page generator: `scripts/generate_de_site.js`.
- Guide service and mail renderer: `server/`.
- Tests: `tests/test_server.py`.
- Nginx, systemd, backup, and deployment instructions: `deploy/`.

## Security and data handling

- Never print, log, expose, or commit `.env` or any token.
- Do not load the project `.env` into another application's settings process.
- Keep `.env` and SQLite databases ignored and restricted to the deploy user.
- Do not expose `data/`, `deploy/`, `server/`, `tests/`, `worker/`, or dotfiles
  through Nginx.
- Tracking must remain disabled until explicit consent and must not collect raw
  personal data.
- Successful guide emails must not be sent twice. Retries are permitted only
  while a send has no `sent_at` timestamp.
- Do not include contact addresses, unsubscribe tokens, or raw subscriber data
  in logs, commits, documentation, or Daniel OS.

## Content rules

- Keep English and German pages aligned in meaning.
- German copy should sound natural and direct, not like a literal translation.
- Preserve the campaign mechanism: explain the reason publicly, choose one to
  seven days, then log out visibly.
- Keep the post suggestions concise and suitable for direct sharing.
- Legal and privacy statements must stay accurate when data processing changes.

## Validation

Use the backend development environment for guide tests and linting when the
runtime-only guide environment does not contain test tools:

```bash
/home/deploy/apps/backend/.venv/bin/python -m pytest -q
/home/deploy/apps/backend/.venv/bin/python -m ruff check server tests
node --check assets/analytics.js
node --check scripts/generate_de_site.js
git diff --check
```

For mail changes, test rendered HTML and plain text, scheduling idempotency,
unsubscribe behavior, and Postmark payload tracking flags. For deployment
changes, run `sudo nginx -t` before reload and verify the relevant systemd
health endpoints afterward.

## Daniel OS

The note mapping and write policy are defined in `.daniel-os.json`. Always show
a German preview and obtain explicit approval before writing notes. Never store
secrets or personal subscriber data in Daniel OS.
