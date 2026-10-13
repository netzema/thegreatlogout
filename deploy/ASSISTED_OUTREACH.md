# Assisted outreach and recovery

## German and English editorial loop (13 October 2026)

Generation uses `server.draft_editor`: draft, independent critique,
at most two targeted revisions, and a critique after each revision. This is at
most six successful model steps for a new draft, five when reviewing an existing
draft. Failed provider calls also consume the shared daily request budget.
The critique checks natural language, personal voice, a supported connection,
one credible request, and factual accuracy. It reports concrete passages and
changes, never an estimated probability of a positive response. German and
English have separate writing, review and revision prompts and strict review
schemas (`natural_german` or `natural_english`). English review summaries and
revision instructions are in German for the owner; quoted passages stay English.

English editing requires the caller to set `review_english=True` on
`draft_editor.run`. `outreach.generate_draft` enables it for new drafts in either
language. Direct editor calls retain the earlier behavior of leaving English
text unchanged unless they explicitly opt in. The opt-in and prompt version are
part of the checkpoint fingerprint, so an old skipped English result cannot be
reused as a completed English review.

The same campaign facts, source quotation, conversation opening, selected mail
thread, writing note, and owner decision notes accompany writing and review.
Historical campaign messages are conversation evidence, not style examples.
The writing guidance favors clear, direct, friendly sentences and an honest
reason for contacting this particular recipient. English guidance uses idiomatic
English rather than translated German sentence structures. No private style-sample
correspondence is included in model requests.

`writing_style.OWNER_EDIT_LESSONS` adds the lessons from the owner's actual edits
before sending: a warm conditional request for relevant support can be personal,
campaign ownership and the wish to keep contacts independently of platforms can
be explicit, and a useful campaign link belongs naturally in the message. German
closing greetings follow the owner's preference for a final comma. These are
preferences, not a mandatory closing template or permission to invent facts.
The one edited English example kept its voice and question and only gained a
campaign-information link; it does not establish a preference for rewriting every
English request as a publicity request. Typographical or grammatical mistakes in
manual edits are not learned. Only these derived lessons enter the writing note;
the private before/after correspondence is not added as style examples to model
requests.

`draft_editor_runs` and append-only `draft_editor_steps` retain successful work
after every model call. Budget exhaustion and network failure resume at the
unfinished stage. A per-stage lease prevents overlapping calls for the same
run. Changing the source context or writing instructions requires a new run.
Changing only the date permits a next-day budget resume; the caller still
checks whether the opportunity remains current.

`server.draft_rewrite.rewrite(id)` reviews an existing German draft;
`rewrite(id, include_english=True)` also permits English drafts to enter the loop.
Sent messages are excluded. It applies a replacement only after a passing critique,
archives the previous version in
`draft_revisions`, resets approval, and preserves `original_body`. Before saving,
it rechecks the draft version, recipient, selected conversation, contact state,
source assessment and writing note. A failed critique remains visible without
replacing the existing text. Held occasions remain held, even if their prose
passes. A stylistic change never establishes recipient relevance.

The Review page shows the current editorial result and unresolved points.
Unresolved or stale assessments block approval and export until the text is
reviewed and edited. Manual text edits archive the previous version and clear
the old assessment; normal human review remains available. Preparation does
not label unresolved text as ready. Existing reply attribution continues to
count only actual replies with explicit message references. Approval, model
judgment and sending alone are not evidence of a positive response.

Database text updates are visible immediately. Timer workers load the new
editor on their next invocation. The running admin process requires the usual
`sudo systemctl restart thegreatlogout-admin.service` to load the new review
metadata and approval checks. No Nginx change is required. The editor itself
never sends, deletes or automatically approves mail.

Historical verification of the first, German-only pass on 13 October: at that
point all nine pending German drafts had been examined, four rewritten and
proofread, and five retained with a specific `no_fit` explanation. After the
bounded model reviews, two texts received a final editorial edit; their prior
automated assessment was cleared, as for any manual text change. The then-current
six English drafts and two sent records matched the pre-edit snapshot. All message
and delivery rows also matched that snapshot; that pass sent or deleted nothing.
Its validation result was 186 passing tests plus Ruff, JavaScript syntax and
whitespace checks. The admin health endpoint was healthy. The text changes had
been stored in production, while activation of the new admin review metadata
still awaited an owner-run restart because passwordless sudo was unavailable.
These counts and activation observations describe that earlier pass, not the
current database or the later English extension.

### Current verification after owner edits and English review

On 13 October, five owner-edited sent messages were compared locally with the
last pre-edit backup. Only the derived style lessons were appended to the live
writing note (version 6). Sent messages were not rewritten.

All 12 then-open occasions were checked against public sources. Five unsuitable
occasions and their five unsent English drafts were removed from the active
queue. One additional stale occasion was dismissed while preserving its already
sent message. Dismissed source identities remain stored to prevent rediscovery.
Six active occasions remain: five already contacted and one newly prepared.
The latter has a verified original article, a public professional contact source,
and an unapproved English draft proofread in the work session.

An additional external model critique was rejected by the environment's approval
review before execution. The new draft therefore has no automated editorial
verdict; ordinary owner review is available. No API request was made in this
pass. The seven sent draft rows, all messages and all delivery records match the
private pre-change backup exactly. No message was sent. Foreign-key checks pass.

Final validation: 197 tests pass, along with Ruff, both required JavaScript
syntax checks and whitespace checks. The active admin process was restarted at
13:58:09 UTC and its health endpoint returns OK. This loads the review interface
and approval checks from the earlier pass. The final language-selection and
scheduled-deferral fixes run in fresh editor/worker processes; they do not add
admin routes. Database text and queue changes are already visible in production.

## Initial rollout (10 October 2026)

Implemented and validated on 10 October 2026. Existing assigned correspondence
now supplies recipient addresses; a separate address-confirmation pass is not
required. The owner approves recipient and text together in Review. The system
prepares messages and never sends outreach automatically.

## Verified state and final activation

- Address inheritance applied to 21 contacts. The retained message queue has no
  unmatched messages. Existing blocks and manually selected addresses survive.
- A real API connection and a real draft for an existing dialogue succeeded.
  The draft remains unapproved. Its campaign mechanism was reviewed and clarified.
- The first broad discovery run created eight new contacts and eight opportunities
  (two events and six publications). A subsequent worker run created one unapproved
  GPT-6.1 Sol draft for a newly discovered contact. Empty results remain valid.
  Six contacts had observed website links, one also a contact-page link. No new
  email addresses or contact permissions were inferred.
- Encrypted external backup uploaded, downloaded, decrypted, checksum-verified
  and restored into isolated temporary databases; both integrity checks passed.
- Both new user timers are installed, enabled and active. Automatic research and
  bounded draft scheduling are configured. The later explicit SMTP extension and its activation status are documented below.
- The base outreach admin was activated at 15:08 UTC and the writing-note editor
  at 15:23 UTC. For future Python route changes, use the restart below. The agent's
  deploy account cannot perform it with passwordless sudo. Broad discovery already
  runs in fresh worker processes. Restart the admin to load the complete-preparation queue routes, immediate worker wakeup and the narrowly scoped progress-script policy for `/opportunities`. Worker processes already load the new pipeline.

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
minutes. With `OUTREACH_AUTOMATION_ENABLED=1`, one daily research job is queued.
Every accepted current opportunity gets a complete preparation job, including
multiple different opportunities for the same organization. Manual research also
queues preparation immediately. The independent limit of three automatic jobs
per UTC date now applies only to additional followups without an opportunity.
The manual button returns visible status and wakes the user worker when
`OUTREACH_WORKER_WAKE_ENABLED=1`. Opportunity cards refresh while work is pending
and link directly to the corresponding review draft. Existing drafts are reused.

A shared file lock prevents worker overlap. Opportunity and context keys prevent
duplicate work. Each worker processes up to 24 jobs, stopping between jobs after
ten minutes; the timer continues remaining work. API-budget exhaustion waits
until the next UTC day instead of discarding work. Interrupted jobs show a
retryable failure, including on the affected opportunity. Retries preserve
completed research and existing drafts. No provider payloads or addresses enter
operational logs.

Research is now broad discovery rather than a search over the contact list.
`server.discovery` performs three independent web-search passes: events/current
happenings/campaigns; publications/studies/media/culture; and public statements,
creators/organizations/viral debates. It searches DACH and international sources
in German and English. No stored contacts or private correspondence are supplied
to these searches or extraction. It also works with an empty contact database.
A fourth API call extracts up to eight source-backed contact/opportunity pairs,
with at most two accepted opportunities per organization per run.

Publications and current debates must be dated within the last 14 days. Upcoming
events may take place in the next 90 days with an announcement from the last
180 days. Both the opportunity and the proposed contact's public identity/role
must reference observed search sources. The server rejects absent/private URLs,
invalid dates, weak fit, and attempts to recreate blocked/paused/closed contacts.
Virality must have supporting evidence, not merely an interesting headline.
Source and claim accuracy still require review; citations are not independent
verification of every model claim.

New contacts are saved as `researched` with permission `unknown`, a source link,
a stated public role, and observed official website/contact-page links where
available. `server.contact_research` fetches those official pages and observed
contact links, falling back to a bounded search for cited official contact pages.
Addresses must occur literally in fetched text or mailto links (including ordinary
at/dot obfuscation). Generic official inboxes or matching named contacts are
preferred. Ambiguous personal contact choices require a model-selected index
from the fetched candidates and a verbatim role/contact quotation from that page;
no model-generated address is accepted. An evidenced name can fill an empty
person field. Redirects and DNS are checked on every fetch, with connections
pinned to public IPs. Fetches have page, response-size and timeout limits.
No reachable, unambiguous address produces a visible partial package with its
draft, rather than a guessed address or a false ready state. The recipient and
text are reviewed together. Existing addresses, chosen people, permissions and contact notes are
preserved. Contact matching happens locally using normalized organization names,
persisted discovery identities and known official domains. Common social/hosting
domains cannot merge unrelated actors. Ambiguous matches are skipped. Discovery
never extends authorized IMAP domains or imports unrelated mail.

Priority is transparent: topic fit (model assessment, 0–75), freshness (0–14,
or 10 for upcoming events), first conversation (10 when no history exists),
and a small review-history adjustment (at most ±5, after five reviewed drafts).
Scores are capped at 100. All current accepted opportunities are prepared,
ordered by score. Separate occasions can have separate drafts for one contact;
standalone followups still avoid an additional active draft for that contact.
Follow-ups still require a due date, an unanswered incoming message, an existing
dialogue after 14 days, or a new opportunity. Expired events cannot generate drafts.

Drafting uses campaign facts, limited notes, the last four non-automated messages
and the chosen opportunity. Each text excerpt is limited to 2,000 characters;
detected email addresses, phone-like numbers, URLs and quoted history are removed.
This reduces data; it is not anonymization. No subscriber database, secrets or
analytics are supplied. Draft generation has no tools. Source material is treated
as data, not instructions. A changed history or new contact block during an API
call prevents saving its stale result. Model output may decline to draft.

### Writing preferences and model choice

The authenticated Settings page offers an editable writing note (up to 6,000
characters). It is stored in `admin.db` and included in encrypted backups.
Concurrent edits are rejected. The note is part of the generation fingerprint:
a change while a request is running prevents saving a stale draft. Existing
reviewed or edited drafts are preserved. The initial note is in
`server/writing_style.py`; the owner's production copy is already persisted.

The note asks for ordinary hyphens, straight apostrophes and double quotation
marks, a lowercase opening after a greeting comma, including English, and no
semicolons. Lists remain allowed, as explicitly clarified by the owner. Deterministic normalization
also enforces these punctuation rules on generated subject/body/rationale and
lowercases openings following common German/English greetings. The model is
explicitly instructed to choose an opening that does not require a capitalized
proper name, English "I", or formal German "Sie". Later sentence starts retain
their normal capitalization. Semicolons that slip through are replaced with commas. These mechanical rules also remain in
force when the free-form note is edited, as explained beside the editor.

Draft context now includes the stored contact person and bounded, redacted
incoming signatures in addition to outgoing salutations. Quoted history stays
excluded. The model uses the current dialogue to identify the actual addressee,
retains the established form of address, and stays neutral when evidence is
ambiguous. Names are personal data, not anonymized identifiers. Generation does
not automatically rewrite contact records; the resulting salutation is reviewed
with the whole draft.

On 10 October 2026, the campaign was changed from GPT-6 Astra to GPT-6.1 Sol for
both drafts and research. Official Standard prices per million input/output
tokens: GPT-6.1 Sol $2/$10, GPT-6 Sol $2/$10, GPT-5.6 Sol $4/$20 (promotional),
GPT-6 Astra $10/$50. These rates cover ordinary contexts, not long-context or
speed premiums; search adds $0.01 per tool call plus retrieved-content tokens.
Sources: [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[pricing](https://developers.openai.com/api/docs/pricing).

GPT-6.1 Sol supports the existing Responses API, structured outputs and web search.
The choice favors the newer Sol at the same ordinary token rates as GPT-6 Sol.
Two real API calls against synthetic German/English conversations verified direct
addressing (including a name absent from the contact record), campaign facts, formatting and
unapproved storage. They used 878/249 and 873/249 input/output tokens respectively,
about $0.00425 per sample before any cache adjustments. A separate real web-search
call completed with sources. These small checks demonstrate compatibility, not
a comprehensive quality comparison or a guarantee of future per-draft costs.

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
| `OUTREACH_AI_MODEL` | `gpt-6.1-sol` |
| `OUTREACH_AI_DAILY_CALLS` | 40, hard upper bound 50; failed requests count |
| `OUTREACH_WORKER_WAKE_ENABLED` | `1` starts the user worker after a manual queue action |
| `OUTREACH_AUTOMATION_ENABLED` | `1` enables automatic daily queueing |
| `OUTREACH_FROM`, `OUTREACH_REPLY_TO` | Campaign sender for exported drafts; inherited from the existing guide configuration |
| `OUTREACH_BACKUP_REMOTE` | Dedicated rclone directory on the authorized Nextcloud remote |

Each request has an output-token cap, a timeout and disabled response storage.
Each search request is limited to two tool calls. A broad research run uses
three searches plus one extraction call, allowing at most six search tool calls
and four API calls within the daily budget. Contact research can add a search and
evidence selection; drafting adds one call per new draft. The former 12-call
default could not cover a complete eight-opportunity batch and has been raised to 40. The call budget is an operational limit,
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

## Complete opportunity packages (10 October 2026)

The complete-preparation update passed 100 Python tests, lint, JavaScript syntax
checks, and the isolated browser flow with 21 responsive route checks. The browser
now also clicks the preparation button, waits for the live status update, follows
the review link and verifies the prepared recipient and draft. Tests cover all
opportunities including several for one contact, duplicate clicks, partial-package
retry, next-day budget resumption, explicit declines, public-address evidence,
unchanged permission/import scope, private DNS and redirect rejection, interrupted
jobs, and the page-specific script policy. The pre-existing guide, review, style
and backup checks remain in the full suite.

All ten existing production opportunities now have a recipient with provenance
and their own unapproved draft. Eight discovered contacts received evidenced
professional addresses, retaining permission `unknown`. No message was sent or
approved. The old unrelated draft was preserved. One remaining source initially
blocked direct fetching; its official programme contact was researched on a
broadcasting partner's programme listing and added as evidence for a successful retry.
All ten prepared drafts pass the saved punctuation and greeting normalization check.

## Validation

The broad discovery update passed the full 81-test Python suite and then all
37 discovery/outreach tests after adjusting queue priorities, plus the browser
flow and its 21 responsive route checks. The base implementation passed 70 Python tests. The lowercase-opening correction
passed all 36 writing-style and outreach tests, including a regression for an
English greeting that preserves later sentence capitalization. A real GPT-6.1 Sol
call with synthetic English correspondence followed the corrected rule before
normalization. The suite exercises guide scheduling/idempotency/unsubscribe/tracking
flags, admin authorization, CSRF, recipient inheritance, conflicts, integrated
review, stale approvals, deferral, source/date validation, duplicate runs,
API budgets, prompt minimization, broad discovery from an empty contact list,
source/date validation, safe contact matching, growth scheduling alongside replies,
upcoming-event expiry, writing-note persistence/CSRF/concurrent edits,
recipient-name evidence, punctuation rules, stale generation, failed jobs, reply attribution and encrypted
backup round-trips including a wrong-key failure. All data in these tests is
synthetic. Real provider and Nextcloud checks are recorded above separately.

The browser fixture in `tests/browser_fixture.py` uses its own database and TLS
certificate under `TGL_BROWSER_FIXTURE`. Run it with the project Python after
creating a one-day self-signed fixture certificate named `cert.pem`/`key.pem`.
`tests/browser_outreach.cjs` uses Playwright (`PLAYWRIGHT_MODULE` can point to an
existing installation). It checks login, new-contact provenance links and opportunity badges,
saving/reloading the writing note, draft creation, deferral, editing,
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

## Approval feedback (11 October 2026)

Approval redirects to the affected draft anchor. Approved cards show the stored
approval and pending manual send prominently, with the export action before the
message and editing forms. Repeating or changing a decision is under a separate
disclosure. Opportunity cards distinguish approval, deferral and pending review;
edited drafts return to the appropriate review state. Approval and export still
create no send record or transport job. Validated with 101 Python tests and the
browser flow including the approval anchor, visible confirmation, export and
21 responsive route checks. Restart the admin service to load the changed route
and opportunity-state handling; templates and styles are read from disk.

## Explicit direct sending (11 October 2026)

`server.outreach_delivery` now implements direct submission through the existing
mailbox. Approval still sends nothing. The additional **Jetzt senden** action
submits exactly the current approved recipient and message. No research job,
timer, approval, export or retry timer invokes SMTP. Postmark remains the guide's
transactional provider. The mailbox is used for these individual reviewed emails.

Configuration belongs only in the campaign's restricted `.env.admin`:

- `OUTREACH_DIRECT_SEND_ENABLED=1` enables the explicit send control after access
  has been verified. Default is disabled.
- `OUTREACH_SMTP_HOST=smtp.mailbox.org` and `OUTREACH_SMTP_PORT=587` use mandatory
  STARTTLS with certificate verification. Port 465 instead uses implicit TLS.
  There is no plaintext fallback.
- `OUTREACH_SMTP_USER` defaults to the configured IMAP identity when unset.
  `OUTREACH_SMTP_PASSWORD` defaults to the IMAP app password only when unset;
  a separate app password with SMTP access can be supplied.
- Existing `OUTREACH_FROM` and `OUTREACH_REPLY_TO` are shown before sending.
  The From identity must be authorized for the sending mailbox.
- Existing IMAP credentials and `OUTREACH_SENT_FOLDER` are used only to check for
  and append the accepted message's Sent copy. The background importer stays
  read-only and its domain scope is unchanged.

The initial probe found that the former app password was not authorized for SMTP.
The owner supplied a replacement with SMTP and IMAP permissions and retired the
old credential. Both campaign settings now use that replacement. A real probe on
port 587 successfully negotiated TLS, authenticated, received a 250 response for
the existing envelope sender, then reset the transaction. IMAP authentication and
read-only access to the Sent folder also succeeded. No RCPT or DATA command was
issued and no message was submitted. Port 465 timed out from this host, so the
verified deployment uses 587. `OUTREACH_DIRECT_SEND_ENABLED=1` is configured;
restart `thegreatlogout-admin.service` to load the routes and environment. Its
root-managed restart still requires the owner's sudo password. The next genuine
send requires the owner's explicit UI click; the agent has sent no live message.

Every draft has one durable delivery record containing its exact MIME snapshot,
recipient, sender, reviewed version, requester and stable Message-ID. An atomic
claim and a per-draft process lock prevent simultaneous clicks. A successful SMTP
DATA acceptance records the outbound message and marks the draft sent once. This
means acceptance by the submission server, not confirmed inbox delivery. Both
plain text and escaped HTML contain the approved words, with no tracking images
or rewritten links. Reply headers preserve the chosen conversation.

Failures before content transmission or explicit server rejections are retryable
only by another explicit send action. An interrupted process or uncertain result
after transmission becomes `unknown`, without an automatic retry. Pending/unknown
submissions block draft edits, recipient changes, exports and manual send logging.
A review-only recovery form requires a documented check of provider evidence.
Absence from Sent alone is not proof of non-delivery. Confirmed non-delivery
invalidates the old approval; a new review is needed before retry. Confirmed delivery
is recorded separately as `smtp-confirmed` rather than claimed as a provider ACK.

An unsuccessful Sent-copy operation does not undo accepted submission. The contact
page offers a separate copy-only retry that first searches for the Message-ID.
It never invokes SMTP. Incoming synchronization deduplicates the copied message
against the already-recorded outbound message. Operators must inspect pending or
unknown submissions after restoring a backup: an older database snapshot cannot
prove that messages sent after that snapshot were not delivered.

Validation includes 119 passing Python tests, the existing guide scheduling,
unsubscribe and tracking checks, and new tests for stale approval, blocked contacts,
CSRF, explicit-send gating, concurrent/duplicate requests, SMTP rejection, ambiguous
network failure, recovery, Sent-copy failure and import deduplication. A real local
SMTP protocol server verified STARTTLS, authentication, MIME transfer and single
submission without external recipients. The isolated direct-delivery browser fixture
checks approval, send, status, Sent copy, duplicate requests and mobile layouts;
it uses synthetic transport only. The existing export/manual-send browser flow
and its 21 responsive route checks also pass.

Official mailbox configuration reference:
[Email configuration](https://kb.mailbox.org/en/business/e-mail/e-mail-configuration/).


### Reply conversations (11 October 2026)

Generated follow-ups choose the latest non-automated message with a valid
Message-ID for the current recipient, including older imported messages outside
the four-message drafting window. Known correspondence with another recipient
is excluded from the automatic selection and drafting context. The selected
message is included in the model context. Assigned legacy history without peer
metadata remains usable.

Review shows the selected conversation and links to its original message. The
editor can select a different message assigned to the same contact or explicitly
start a new conversation. Reply drafts retain the original subject (with `Re:`
when needed); saving any change invalidates approval. SMTP rendering never
silently changes an approved subject or body.

SMTP, EML export and manual send logging share the reply metadata. `In-Reply-To`
identifies the selected message and `References` preserves its ancestor chain.
Missing chains can be reconstructed from locally assigned messages. Invalid IDs
are excluded, cycles terminate, and very long chains retain the root and most
recent links (30 total). Sent records retain these headers for later follow-ups.
This follows [RFC 5322 section 3.6.4](https://www.rfc-editor.org/rfc/rfc5322#section-3.6.4).
The receiving mail client's settings ultimately control conversation display.
Existing accepted deliveries are immutable and are never resent by this change.

The admin service needs a restart to load this Python update. The root-managed
restart requires the owner's sudo password. Validation covers reply selection,
subject preservation, cross-contact and malformed-header rejection, switching to
a new conversation, approval invalidation, identical export/SMTP headers, and
thread continuity after both direct and manually logged delivery. The isolated
browser fixture supports `TGL_BROWSER_THREAD=1` for an existing conversation.

Validated with 128 passing Python tests and the threaded direct-send browser flow,
including desktop/mobile layouts and duplicate-send protection. Two existing
unsent reply drafts received the matching conversation subject and a new version;
their bodies and all accepted delivery records were preserved. A restricted local
SQLite backup was taken before the update. No live email was sent for testing.


## Conservative opportunity qualification and capitalization (11 October 2026)

The owner's revised policy prioritizes fit over volume: there is time to wait for
an appropriate occasion. `server.opportunity_quality` evaluates direct campaign
fit, the actor's relevant responsibility, and a concrete useful opening (each
0–3). The displayed score weights these dimensions 45/20/35. Freshness, fame,
novelty and earlier approvals cannot compensate for a weak topic or opening.
Recommendation requires direct fit 3, responsibility and opening at least 2,
a concrete starting point, and a verbatim supporting excerpt in the supplied
source text. Scores are model judgments, not probabilities of success.

New discovery only creates contacts and preparation jobs for qualifying results.
Existing occasions can be classified as good, watch, poor or unassessed.
Recommendations and Review are sorted by fit. Held proposals remain accessible
in separate views with their explanation, but cannot be approved, exported or
sent. The scheduler and draft generator also reject held occasions. Reassessment
invalidates their previous approvals, preserves draft wording and sent records,
and respects in-flight/unknown delivery locks. Manually entered occasions without
an automatic source key remain reviewable until explicitly assessed.

Existing open occasions were reassessed against freshly fetched public sources,
without contact addresses, correspondence or earlier model rationales in the
assessment prompt. Unreadable sources produce a conservative watch state.
Of 15 assessed occasions, 5 qualified, 6 were held for observation and 4 lacked a
sufficient basis. These are dated assessment results, not permanent judgments.
The repeatable maintenance entry point `python -m server.opportunity_quality`
processes open occasions not yet assessed, respects the existing daily API limit,
and prints only aggregate progress. Individual reassessment uses `assess(id)`.
A new, evidenced occasion can make a later contact appropriate.

The writing note now explicitly exempts required capitalization: proper names,
German nouns and nominalizations, acronyms, English I and formal Sie/Ihr/Ihnen.
Mechanical normalization only lowercases known ordinary opening words and
preserves unknown words and acronyms. Model instructions apply the grammatical
rule in context. The stored writing note was updated without replacing other
preferences. Existing draft bodies were not regenerated.

Validation: 153 Python tests passed, including qualification thresholds, source
quotes, blocked approval/export/transport, scheduling, ordering and capitalization
exceptions. The isolated quality browser test passed recommendation/held filters,
disabled approval, direct links and desktop/mobile layouts. A private SQLite
snapshot was taken before updating the stored note and assessments. No real mail
was sent. Runtime route changes require restarting the root-managed admin service.
This work was implemented alongside pre-existing UI changes, which were preserved.
