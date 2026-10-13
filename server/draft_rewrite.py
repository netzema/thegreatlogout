"""Versioned editorial updates of existing drafts. No mailbox or send operations."""

import json

from server import admin_db as storage
from server import draft_editor, mail_threads, opportunity_quality as quality, outreach


def snapshot(db, did):
    from server.outreach_delivery import assert_editable

    row = db.execute("SELECT * FROM drafts WHERE id=?", (did,)).fetchone()
    if not row or row["status"] not in {"draft", "approved", "deferred"}:
        raise ValueError("Nur offene Entwürfe können überarbeitet werden")
    assert_editable(db, did)
    assert_editable(db, contact_id=row["contact_id"])
    if (
        db.execute("SELECT 1 FROM messages WHERE draft_id=?", (did,)).fetchone()
        or db.execute(
            "SELECT 1 FROM outreach_deliveries WHERE draft_id=? AND status='sent'",
            (did,),
        ).fetchone()
    ):
        raise ValueError("Eine versendete Nachricht wird nicht überarbeitet")
    context, fingerprint, _ = outreach.draft_context(
        db,
        row["contact_id"],
        row["opportunity_id"],
        reply_id=row["reply_message_id"],
        text_review=True,
    )
    if row["opportunity_id"]:
        occasion = db.execute(
            "SELECT * FROM opportunities WHERE id=?", (row["opportunity_id"],)
        ).fetchone()
        context["occasion_review"] = {
            "allowed": quality.allowed(occasion)
            and outreach.current_opportunity(occasion, max_age=30),
            "reason": occasion["score_reason"],
        }
    return dict(row), context, outreach.digest([dict(row), fingerprint])


def archive(db, row):
    db.execute(
        "INSERT OR IGNORE INTO draft_revisions "
        "(draft_id,version,subject,body,rationale,created_at) VALUES (?,?,?,?,?,?)",
        (
            row["id"],
            row["version"],
            row["subject"],
            row["body"],
            row["rationale"],
            storage.now(),
        ),
    )


def rewrite(did, *, candidate=None, expected_version=None, include_english=False):
    """Review authorized drafts, including held texts; never improve their fit status."""
    with storage.database() as db:
        before, context, key = snapshot(db, did)
    if expected_version is not None and before["version"] != expected_version:
        raise ValueError("Entwurf wurde seit dem Gegenlesen geändert")
    language = draft_editor.detect_language(before["body"])
    if language == "en" and not include_english:
        return "english"
    if (
        candidate is None
        and before["editorial_status"]
        and before["editorial_version"] == before["version"]
    ):
        return before["editorial_status"]
    seed = candidate or {
        "should_draft": True,
        "subject": before["subject"],
        "body": before["body"],
        "rationale": before["rationale"] or "Bestehender Entwurf zur erneuten Prüfung.",
        "framing": before["framing"],
    }
    instructions = outreach.draft_instructions(context) + (
        f" Überarbeite einen bestehenden {'deutschen' if language == 'de' else 'englischen'} Entwurf. Der alte Text ist Rohmaterial, "
        "kein Stilvorbild und kein Beleg für Fakten oder Angebote. Bei einem zurückgestellten "
        "Anlass gilt die bestehende Sperre unverändert. Erfinde keine Verbindung, um einen "
        "Text zu retten. Prüfe den konkreten Grund für eine Antwort."
    )
    outcome = draft_editor.run(
        "rewrite:"
        + outreach.digest(
            [key, seed, instructions, draft_editor.PROMPT_VERSION, include_english]
        ),
        context,
        instructions,
        seed=seed,
        language=language,
        review_english=include_english,
    )
    candidate = outreach.DraftResult.model_validate(outcome.candidate)
    report = {**outcome.review, "revisions": outcome.rounds}
    if (
        outcome.status != "ready"
        and candidate.should_draft
        and candidate.body != before["body"]
    ):
        report["unapplied_candidate"] = {
            "subject": candidate.subject,
            "body": candidate.body,
        }
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        current, _, current_key = snapshot(db, did)
        if current_key != key:
            raise ValueError(
                "Entwurf oder Kontext wurde während der Überarbeitung geändert"
            )
        archive(db, current)
        # A failed critique stays visible, without replacing the owner's existing text.
        subject = candidate.subject if outcome.status == "ready" else current["subject"]
        body = candidate.body if outcome.status == "ready" else current["body"]
        rationale = (
            candidate.rationale if outcome.status == "ready" else current["rationale"]
        )
        if current["reply_message_id"]:
            subject = mail_threads.subject(
                mail_threads.selected(
                    db, current["contact_id"], current["reply_message_id"]
                )
            )
        db.execute(
            "UPDATE drafts SET subject=?,body=?,rationale=?,version=version+1,"
            "status='draft',approved_recipient='',review_at=NULL,updated_at=?,"
            "editorial_status=?,editorial_report=?,editorial_version=version+1 "
            "WHERE id=? AND version=?",
            (
                subject,
                body,
                rationale,
                storage.now(),
                outcome.status,
                json.dumps(report, ensure_ascii=False),
                did,
                before["version"],
            ),
        )
    return outcome.status
