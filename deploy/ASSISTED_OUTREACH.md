# Assisted outreach and recovery

Implemented and validated on 10 October 2026. Existing assigned correspondence
now supplies recipient addresses; a separate address-confirmation pass is not
required. The owner approves recipient and text together in Review. The system
prepares messages and never sends outreach automatically.

## Verified state and final activation

- Address inheritance applied to 21 contacts. The retained message queue has no
  unmatched messages. Existing blocks and manually selected addresses survive.
- A real API connection and a real draft for an existing dialogue succeeded.
  The draft remains unapproved. Its campaign mechanism was reviewed and clarified.
- The real research/extraction flow completed without accepting an insufficiently
  supported current opportunity. Empty results are a valid outcome.
- Encrypted external backup uploaded, downloaded, decrypted, checksum-verified
  and restored into isolated temporary databases; both integrity checks passed.
- Both new user timers are installed, enabled and active. Automatic research and
  bounded draft scheduling are configured; no outreach transport is installed.
- The updated admin process still needs the root restart below. The agent's
  deploy account cannot perform it with passwordless sudo. New template controls
  are hidden until the process loads the new routes.

```bash
sudo systemctl restart thegreatlogout-admin.service
systemctl is-active thegreatlogout-admin.service
curl --fail https://admin.thegreatlogout.org/health
```

No Nginx configuration change or reload is needed for this extension. Visit
`/outreach`, `/review` and `/settings` after restart. No real send is needed for
the software checks. A live delivery test remains subject to the owner's final
approval of the actual recipient and text.

## Recipient and review behavior

`server.contact_history` derives addresses only from already assigned messages,
without widening the IMAP import boundary. A single counterpart is stored with
its message provenance. The latest usable outbound address becomes the default
only when no address has already been selected. Other observed addresses are
retained for future matching. Conflicting contact assignments or multiple peers
in one message are surfaced for review instead of guessed.

Prior outgoing correspondence gives a contact the `existing` status; this is
evidence of a previous conversation, not mailing-list consent. Unknown recipients
can be confirmed directly in draft Review. Blocked/paused contacts and unreviewed
objection hints cannot be approved/exported. All drafts remain unapproved until
the owner acts. Recipient changes invalidate other pending approvals; text
changes invalidate the edited draft. Stale versions are rejected. Deferral has
a date (seven days by default) and returns the same draft to Review when due.

Exported `.eml` files contain an unsent marker and a version-specific Message-ID.
Follow-ups can reference the latest own sent message as well as an incoming one.
The user must send them in the mail client. If that Message-ID survives delivery,
Sent-folder import records the actual send once and allows explicit reply
attribution. Mail clients that replace it require manual send logging. Export
alone never creates a send record.

## Research, drafts and scheduling

The deploy user's `thegreatlogout-outreach.timer` checks the queue every five
minutes. With `OUTREACH_AUTOMATION_ENABLED=1`, one daily research job and at most
three automatic draft jobs per UTC date are queued. Explicitly requested draft
jobs can exceed that count but remain within the API call limit. A shared file
lock prevents worker overlap. Source/contact keys deduplicate opportunities;
contact/context fingerprints deduplicate generated drafts and jobs across reruns.
Interrupted jobs become visible failures. Failed jobs can be retried explicitly
up to three attempts; failures do not log provider payloads or contact data.

Research sends organization names and categories to OpenAI web search. A second
structured extraction pass proposes at most five opportunities. The server
rejects unknown contacts, sources absent from the search evidence, private URL
forms, future/older-than-14-day dates and weak-fit proposals. Sources remain
clickable and their accuracy/relevance is part of review; a citation is not an
independent verification of every model claim.

Priority is transparent: topic fit (model assessment, 0–60), freshness (0–14),
existing dialogue (0 or 10), contact priority (3–9), and a small review-history
adjustment (at most ±5, only after five reviewed drafts for that framing).
Follow-ups require a due date, an unanswered incoming message, an existing
dialogue after 14 days, or a new opportunity. Repeatedly unanswered contacts
without a new reason do not receive automatic reminders.

Drafting uses campaign facts, limited notes, the last four non-automated messages
and the chosen opportunity. Each text excerpt is limited to 2,000 characters;
detected email addresses, phone-like numbers, URLs and quoted history are removed.
This reduces data; it is not anonymization. No subscriber database, secrets or
analytics are supplied. Draft generation has no tools. Source material is treated
as data, not instructions. A changed history or new contact block during an API
call prevents saving its stale result. Model output may decline to draft.

The Outreach page shows decisions, edits, sends, explicitly attributable replies,
next actions, queue state and daily token counts. Review experience gently
influences priority; it never automatically changes permissions or approves mail.
Historical inbound messages are not falsely attributed to new drafts.

## Independent configuration

All settings belong in this repository's mode-600 `.env.admin`, never in Git.
An existing API credential was copied once with the owner's authorization; no
runtime code reads another application's settings or database.

| Variable | Purpose / default |
| --- | --- |
| `OPENAI_API_KEY` | Campaign-owned copy of the authorized API credential |
| `OUTREACH_AI_MODEL` | `gpt-6-astra` |
| `OUTREACH_AI_DAILY_CALLS` | 12, hard upper bound 50; failed requests count |
| `OUTREACH_AUTOMATION_ENABLED` | `1` enables automatic daily queueing |
| `OUTREACH_FROM`, `OUTREACH_REPLY_TO` | Campaign sender for exported drafts; inherited from the existing guide configuration |
| `OUTREACH_BACKUP_REMOTE` | Dedicated rclone directory on the authorized Nextcloud remote |

Each request has an output-token cap, a timeout and disabled response storage.
Search is limited to two tool calls. The call budget is an operational limit,
not a euro-denominated spending cap; enforce a monetary budget at the provider
as needed. OpenAI's abuse-monitoring retention still applies. References:
[web search](https://developers.openai.com/api/docs/guides/tools-web-search),
[structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[data controls](https://developers.openai.com/api/docs/guides/your-data).

## Encrypted external recovery

`thegreatlogout-offsite-backup.timer` runs daily at 04:15 Europe/Vienna, plus up
to five minutes of jitter. `server.offsite_backup` creates consistent SQLite
snapshots, adds the analytics key and both campaign environment files, creates
a SHA-256 manifest, and encrypts the archive with GnuPG AES-256. Only ciphertext
is uploaded to `Backups/TheGreatLogout` on the authorized Nextcloud remote.
Every run downloads its archive, compares the encrypted bytes, decrypts into
a private temporary directory, checks each manifest entry and both SQLite
integrity checks. Temporary plaintext is removed on exit. Old archives with the
campaign prefix rotate after 14 days; other remote files are untouched.

The generated recovery key is in `data/backup-recovery.key` (mode 600), excluded
from archives. The owner must download it through the authenticated Settings
page and retain it separately, for example in a password manager. Until that
copy is held independently, loss of the entire server also loses the recovery
key. Never paste the key in chat, logs, notes or Git.

To verify an archive after retrieving it with rclone, use
`server.offsite_backup.verify_archive(Path(...), key=Path(...))` from this
repository's Python environment. That routine never replaces live files.
For an actual recovery: stop guide, admin and all campaign workers; preserve the
current files; decrypt to a private staging directory; validate the manifest and
databases; restore databases, the matching analytics key and secrets with owner
deploy/mode 600; remove only the preserved stale WAL/SHM files; restart services
and check health. Do not replay mail merely because a backup was restored: inspect
delivery state before re-enabling the guide send timer.

## Validation

61 Python tests passed. The suite exercises guide scheduling/idempotency/unsubscribe/tracking
flags, admin authorization, CSRF, recipient inheritance, conflicts, integrated
review, stale approvals, deferral, source/date validation, duplicate runs,
API budgets, prompt minimization, failed jobs, reply attribution and encrypted
backup round-trips including a wrong-key failure. All data in these tests is
synthetic. Real provider and Nextcloud checks are recorded above separately.

The browser fixture in `tests/browser_fixture.py` uses its own database and TLS
certificate under `TGL_BROWSER_FIXTURE`. Run it with the project Python after
creating a one-day self-signed fixture certificate named `cert.pem`/`key.pem`.
`tests/browser_outreach.cjs` uses Playwright (`PLAYWRIGHT_MODULE` can point to an
existing installation). It checks login, draft creation, deferral, editing,
approval, export, synthetic delivery logging and logout, and seven admin routes
at 1440, 390 and 320 px without page errors or document overflow. It never uses
production credentials or sends mail.

```bash
/home/deploy/apps/backend/.venv/bin/python -m pytest -q
/home/deploy/apps/backend/.venv/bin/python -m ruff check server tests
node --check assets/analytics.js
node --check scripts/generate_de_site.js
git diff --check
```
