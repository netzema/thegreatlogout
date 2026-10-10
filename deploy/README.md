# Independent campaign deployment

The live campaign deployment runs entirely from this repository and its own `.venv`:

- Public static website: `thegreatlogout.org`, served by Nginx.
- Guide API: `server.app:app` on `127.0.0.1:8788`, existing service and 15-minute timer.
- Admin and analytics collector: `server.admin:app` on `127.0.0.1:8789`, exposed at `admin.thegreatlogout.org`.
- Public analytics endpoint `/api/analytics/events` proxies to the campaign admin on 8789. It requires the campaign Origin and explicit consent cookie.
- Guide database: `data/thegreatlogout.db`, unchanged by this migration.
- Admin database: `data/admin.db` for accounts, sessions, contacts, opportunities, drafts, review decisions, mail history, sync cursors and analytics.
- Independent analytics HMAC key: `data/analytics.key`.
- Independent daily retention and backup job; no NDS application imports, settings, database connections or network calls at runtime.

## Migration and activation

Production cutover completed on 10 October 2026. The owner confirmed execution and testing of the activation script and changed the imported password in the independent admin. Follow-up checks confirmed HTTPS health for admin and guide, active admin/guide/guide-timer/maintenance-timer units, and public analytics routing to port 8789. The database contains 21 seeded organizations and 21 migrated analytics events. Mailbox credentials are configured. The deploy user's five-minute mailbox timer is enabled and active with lingering enabled; the system mailbox timer remains disabled to avoid duplicate scheduling. The initial header scan of INBOX and Sent is complete: one campaign message was imported and remains unmatched. The owner then corrected the historical sender identity. A one-time import restricted to the exact confirmed address and an explicit campaign subject added 26 sent messages and one inbound message from Sent/INBOX. That snapshot has since been reconciled by the owner: 27 retained messages are assigned, with no unmatched messages, across 22 contact records. Assigned outbound history supplies recipient addresses automatically; no second address-confirmation pass is required. Twelve additional subject matches in Trash were left untouched. The regular worker retains its campaign-domain boundary; the personal sender identity is not documented here.

The authorized one-time admin import copies the existing active account's email and password hash, never its password or NDS application secrets. New sessions and subsequent password changes are independent. The analytics import copies only The Great Logout events within the 90-day retention period, with event-ID deduplication. The source databases are opened read-only. Existing visitor hashes are preserved, while new events use a new campaign-owned key; unique visitors spanning the cutover can therefore be counted twice.

Installation as deploy:

```bash
cd /home/deploy/apps/thegreatlogout.org
.venv/bin/python -m pip install -r server/requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check server tests
```

Initial migration, only when authorized to copy the source admin:

```bash
.venv/bin/python -m server.bootstrap_admin \
  --user-source /home/deploy/apps/backend/data/app.db \
  --analytics-source /home/deploy/apps/backend/data/analytics.db
```

This command is repeatable and never overwrites independently changed passwords or contact notes. It seeds the 21 organizations confirmed by the owner, without personal addresses or invented message dates. Existing historical references to other organizations are not represented as verified imports.

Activate as root after DNS points at this server:

```bash
sudo bash /home/deploy/apps/thegreatlogout.org/deploy/activate-independent-admin.sh
```

The script installs the independent service, validates local health, obtains a separate Let's Encrypt certificate using the existing ACME account, validates Nginx before every reload, switches the public collector and enables daily backups. It makes one final idempotent analytics catch-up import. It preserves the guide service and guide timer, creates a rollback snapshot under `/var/backups/`, and restores old Nginx routing on activation failure. The mailbox timer is installed but remains disabled until credentials are configured.

Verify:

```bash
sudo nginx -t
systemctl is-active thegreatlogout-admin thegreatlogout-guide thegreatlogout-send-due.timer thegreatlogout-maintenance.timer
curl --fail https://admin.thegreatlogout.org/health
curl --fail https://api.thegreatlogout.org/health
```

In a browser, sign in with the imported account. Check Review, Contacts, Webanalyse, Guide and Settings. Confirm public analytics make no requests before consent, then verify accepted consented events appear in the new dashboard. No real guide signup or outreach send is required for deployment verification.

## Administration and outreach

The admin supports contact creation/editing, categories, contact permission, priority, follow-up dates, opportunities, message history, drafts, versioned review decisions, explicit reply references, `.eml` draft export, manual send logging and reply review. Editing a draft invalidates its approval. Existing correspondence supplies the contact address and the `existing` contact status. Recipient and text are approved together in Review. Unknown contacts can be confirmed within that same Review; blocked contacts and unreviewed objection hints prevent approval/export. Exporting never sends or marks a message sent. Only confirm manual delivery after it actually occurred.

Review messages can create a new contact and assign the message in one transaction; a single peer address is suggested for human verification and permission defaults to unknown. Unmatched and matched messages can be explicitly removed from the outreach database. Removal does not change the source mailbox. Only a SHA-256 fingerprint of the Message-ID (or the existing raw-message digest fallback) is retained to prevent reimport; body, addresses, subject and derived hints are removed from the active message table. Existing local backups expire under the normal 14-day rotation. Dependent reply drafts lose their reply reference and unsent approvals, while their independently authored text remains. Message forms are bound to the displayed record to protect against stale tabs and SQLite row-ID reuse.

The assisted-outreach extension is described in `ASSISTED_OUTREACH.md`. Its schema migration and address inheritance have been applied. The updated admin routes require `sudo systemctl restart thegreatlogout-admin.service`; the current agent cannot run that root operation without the owner's password. Templates hide new controls until the updated process starts. The migration remains additive and repeatable.

This release deliberately has no automated outreach transport. The existing Postmark integration remains solely the guide's transactional sender. The appropriate provider and permission basis for any future outreach transport must be resolved before enabling it. Local extractive review hints identify questions and possible contact objections and hide quoted history in the preview. These hints do not change permission, approve drafts or send messages. Source-backed research, bounded AI drafts, follow-up suggestions and review-based prioritization are implemented by `server.outreach`; they never send messages. See `ASSISTED_OUTREACH.md` for activation, limits and verified behavior.

## Campaign mailbox sync

Create `/home/deploy/apps/thegreatlogout.org/.env.admin` with mode 600, owned by deploy. Do not put its values in prompts, documentation, Git or Daniel OS. Supported variable names:

- `ADMIN_ORIGIN` (default `https://admin.thegreatlogout.org`)
- `OUTREACH_IMAP_HOST` (default `imap.mailbox.org`)
- `OUTREACH_IMAP_USER`
- `OUTREACH_IMAP_PASSWORD` (a dedicated mailbox app password)
- `OUTREACH_SENT_FOLDER` (default `Sent`; verify the actual folder name)
- `OUTREACH_ALLOWED_DOMAINS` (this deployment allows only `thegreatlogout.org`)

The worker fetches only selected headers and size first. Only mail to the exact campaign domain, or mail sent from it in Sent, may have its body fetched. It uses read-only folders and `BODY.PEEK` so it does not mark messages read. Private mail retains no header or body data. Large messages above 2 MB are skipped. Imported bodies are plain text, capped at 20,000 characters; attachments and HTML are not loaded separately or rendered. UIDVALIDITY/UID checkpoints and Message-ID deduplication make reruns safe. Matching uses known message references, explicit contact addresses and verified organization-domain mappings; ambiguous matches enter the unmatched queue. A reconciliation pass resolves replies imported before their corresponding sent messages. Historical replies explicitly answered later in the same contact thread are marked reviewed. A shared file lock prevents overlapping user, system and manual runs. Routine auto replies are recorded but do not become normal reply reviews.

After credentials and folder names have been verified:

```bash
mkdir -p ~/.config/systemd/user
install -m 644 deploy/user/thegreatlogout-mail-sync.service ~/.config/systemd/user/
install -m 644 deploy/user/thegreatlogout-mail-sync.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user start thegreatlogout-mail-sync.service
systemctl --user enable --now thegreatlogout-mail-sync.timer
systemctl --user show thegreatlogout-mail-sync.service -p Result -p ExecMainStatus
systemctl --user list-timers thegreatlogout-mail-sync.timer
```

The deployed user timer runs every five minutes plus up to 30 seconds of jitter after a completed run. `loginctl show-user deploy -p Linger` must report `yes` for operation across logout and boot; it already does on this server. On a new server an administrator can enable this with `sudo loginctl enable-linger deploy`. Keep the system-level mailbox timer disabled; the system service remains available for manual runs. Missing credentials cause a failed job instead of a misleading success. First import is bounded to 200 messages per folder per run. Job status appears in the dashboard. For assisted drafts only, limited and redacted campaign excerpts can be submitted to the separately configured OpenAI API. Research receives public organization names and categories, and no guide subscriber data is supplied. No raw payloads are logged. An explicitly invoked historical import can pass a confirmed former address to the importer; it additionally requires an unambiguous campaign subject and is never enabled by the regular worker. Historical imports must preserve the same header-first, read-only body-fetching boundary and must not turn a personal domain into a general allowlist.

## Backups and recovery

`thegreatlogout-maintenance.timer` runs daily. It purges expired sessions and analytics older than 90 days, then uses SQLite's online backup API for consistent copies of both campaign databases under `data/backups/` (mode 700, files 600). Every backup is integrity-checked. Local snapshots rotate after 14 days; expired analytics are also pruned from retained admin snapshots. Encrypted external copies now include both databases, the analytics key and the campaign environment files, stored in the dedicated Nextcloud backup folder. Each upload is downloaded, authenticated/decrypted and restored into isolated temporary files for database integrity checks. Both local and external snapshots rotate after 14 days. The recovery key must additionally be kept by the owner outside this server; it is downloadable through the protected Settings page after the admin restart.

Restore with services stopped: preserve the current database files first; run `PRAGMA integrity_check` against the chosen backup; replace the target database, remove only its stale WAL/SHM after preserving them, set owner deploy and mode 600, then restart services and verify health. Restore the matching analytics key from separate protected storage when recovering onto a new server. Never expose or commit backup data.

The old NDS analytics records are left unchanged as rollback history; they are not read by the campaign at runtime. The previous NDS backup integration is obsolete for campaign recovery and its deploy examples have been removed from this repository.

## Validation on 10 October 2026

- 30 isolated Python tests passed, including unchanged guide scheduling, unsubscribe and Postmark tracking-flag checks; admin access, CSRF, review-version conflicts, changed-recipient invalidation, explicit reply threading, import deduplication, domain filtering, bounded mailbox backfill, UIDVALIDITY resets, read-only body fetching, local review hints and backup integrity.
- Ruff, JavaScript syntax, shell syntax and `git diff --check` passed.
- Eight admin routes checked at 1440, 390 and 320 px with synthetic data, plus browser login, draft creation and deferral. No page errors or horizontal overflow.
- systemd unit verification passed; both Nginx vhosts passed an isolated syntax test with a temporary certificate and unprivileged ports.
- The owner completed and tested the root activation script, which validates production Nginx before reload. Independent follow-up checks confirmed successful public HTTPS health responses, the intended vhost routing and active campaign services. The latest backup/retention job reports success; the five-minute user mailbox timer is active and repeated syncs complete without duplicate imports. No outreach messages were sent.
