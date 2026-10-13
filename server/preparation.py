"""One review package per opportunity, with resumable contact research and drafting."""

import json

from server import admin_db as storage
from server import contact_research, opportunity_quality as quality


def editorial_summary(draft):
    """Expose only the current, structured editorial report to the review screen."""
    draft = dict(draft)
    status = draft.get("editorial_status", "")
    current = bool(status) and draft.get("editorial_version") == draft["version"]
    try:
        report = json.loads(draft.get("editorial_report", "{}"))
    except (ValueError, TypeError):
        report = {}
    if not isinstance(report, dict):
        report = {}
    issues = report.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    candidate = report.get("unapplied_candidate")
    if not isinstance(candidate, dict) or not all(
        isinstance(candidate.get(key), str) for key in ("subject", "body")
    ):
        candidate = None
    return {
        "status": status,
        "current": current,
        "unresolved": bool(status)
        and (not current or status in {"needs_review", "no_fit"}),
        "summary": str(report.get("summary", ""))[:1500],
        "issues": [item for item in issues if isinstance(item, dict)][:8],
        "candidate": candidate,
    }


def editorial_note(draft):
    review = editorial_summary(draft)
    if not review["current"]:
        return "Die Textprüfung gehört zu einer älteren Version. Bitte den aktuellen Entwurf prüfen."
    return review["summary"] or (
        "Für diese Nachricht fehlt ein überzeugender Gesprächseinstieg. Bitte den Entwurf prüfen."
        if review["status"] == "no_fit"
        else "Die Textprüfung hat offene Punkte gefunden. Bitte den Entwurf überarbeiten."
    )


def state(db, oid, status, note, draft_id=None):
    db.execute(
        "UPDATE opportunities SET preparation_state=?,preparation_note=?,preparation_draft_id=coalesce(?,preparation_draft_id) WHERE id=?",
        (status, note, draft_id, oid),
    )


def enqueue(db, cid, oid, *, retry=False):
    from server.outreach import draft_context

    draft_context(db, cid, oid)
    job = db.execute(
        "SELECT * FROM automation_jobs WHERE dedup_key=?", (f"prepare:{oid}",)
    ).fetchone()
    if job:
        if retry and job["status"] in {"failed", "done"}:
            db.execute(
                "UPDATE automation_jobs SET status='queued',result='',finished_at=NULL WHERE id=?",
                (job["id"],),
            )
            state(db, oid, "queued", "Kontakt und Anschreiben werden vorbereitet.")
            return 1
        return 0
    db.execute(
        "INSERT INTO automation_jobs(kind,contact_id,opportunity_id,dedup_key,created_at) VALUES ('prepare',?,?,?,?)",
        (cid, oid, f"prepare:{oid}", storage.now()),
    )
    state(db, oid, "queued", "Kontakt und Anschreiben werden automatisch vorbereitet.")
    return 1


def run(cid, oid):
    from server.outreach import draft_context, generate_draft

    with storage.database() as db:
        draft_context(db, cid, oid)
        state(
            db,
            oid,
            "running",
            "Kontaktadresse recherchieren und Anschreiben vorbereiten …",
        )
        existing = db.execute(
            "SELECT * FROM drafts WHERE opportunity_id=? ORDER BY id DESC LIMIT 1",
            (oid,),
        ).fetchone()
        if existing and existing["status"] in {"sent", "rejected"}:
            state(
                db,
                oid,
                "reviewed",
                "Dieser Vorschlag wurde bereits entschieden.",
                existing["id"],
            )
            return 0
    address_ready = contact_research.enrich(cid)
    count = 0 if existing else generate_draft(cid, oid)
    with storage.database() as db:
        # Recheck after API work. A concurrent dismissal/objection must not become ready.
        draft_context(db, cid, oid)
        draft = db.execute(
            "SELECT * FROM drafts WHERE opportunity_id=? ORDER BY id DESC LIMIT 1",
            (oid,),
        ).fetchone()
        address_ready = address_ready and bool(
            db.execute("SELECT email FROM contacts WHERE id=?", (cid,)).fetchone()[0]
        )
        if draft and editorial_summary(draft)["unresolved"]:
            state(db, oid, "needs_attention", editorial_note(draft), draft["id"])
        elif draft and address_ready:
            state(
                db,
                oid,
                "ready",
                "Kontaktadresse und Anschreiben sind vorbereitet. Bitte gemeinsam prüfen und freigeben.",
                draft["id"],
            )
        elif draft:
            state(
                db,
                oid,
                "needs_attention",
                "Anschreiben vorbereitet. Auf den erreichbaren offiziellen Quellen konnte keine eindeutige berufliche E-Mail-Adresse belegt werden.",
                draft["id"],
            )
        else:
            note = db.execute(
                "SELECT preparation_note FROM opportunities WHERE id=?", (oid,)
            ).fetchone()[0]
            state(
                db,
                oid,
                "needs_attention",
                note
                if note and not note.endswith("…")
                else "Es konnte kein passender Entwurf erstellt werden. Bitte erneut vorbereiten.",
            )
    return count


def refresh(db):
    """Reflect review decisions and manual recipient edits without another AI call."""
    for o in db.execute(
        "SELECT o.*,c.email FROM opportunities o JOIN contacts c ON c.id=o.contact_id WHERE o.preparation_draft_id IS NOT NULL AND o.status='open'"
    ).fetchall():
        draft = db.execute(
            "SELECT * FROM drafts WHERE id=?", (o["preparation_draft_id"],)
        ).fetchone()
        if not draft:
            continue
        if draft["status"] != "sent" and not quality.allowed(o):
            state(
                db,
                o["id"],
                "held",
                "Kein ausreichend belegter Gesprächseinstieg. Vorerst nicht anschreiben.",
            )
            continue
        if draft["status"] == "sent":
            state(db, o["id"], "sent", "Versand im Kontaktverlauf protokolliert.")
        elif draft["status"] == "rejected":
            state(
                db, o["id"], "reviewed", "Dieser Vorschlag wurde bereits entschieden."
            )
        elif draft["status"] == "approved":
            delivery = db.execute(
                "SELECT status,note FROM outreach_deliveries WHERE draft_id=?",
                (o["preparation_draft_id"],),
            ).fetchone()
            if delivery and delivery["status"] in {"sending", "unknown", "failed"}:
                state(
                    db,
                    o["id"],
                    {
                        "sending": "sending",
                        "unknown": "send_unknown",
                        "failed": "send_failed",
                    }[delivery["status"]],
                    delivery["note"] or "Versand läuft. Bitte Status im Review prüfen.",
                )
            else:
                state(
                    db,
                    o["id"],
                    "approved",
                    "Empfänger und Text sind freigegeben. Noch nicht versendet. Nächster Schritt im Review.",
                )
        elif draft["status"] == "deferred":
            state(
                db,
                o["id"],
                "deferred",
                "Dieser Entwurf ist bis zur Wiedervorlage zurückgestellt.",
            )
        elif editorial_summary(draft)["unresolved"]:
            state(db, o["id"], "needs_attention", editorial_note(draft))
        elif o["preparation_state"] in {
            "ready",
            "needs_attention",
            "approved",
            "deferred",
            "reviewed",
            "sent",
            "sending",
            "send_unknown",
            "send_failed",
        }:
            if o["email"]:
                state(
                    db,
                    o["id"],
                    "ready",
                    "Kontaktadresse und Anschreiben sind vorbereitet. Bitte gemeinsam prüfen und freigeben.",
                )
            else:
                state(
                    db,
                    o["id"],
                    "needs_attention",
                    "Anschreiben vorbereitet. Eine belegte berufliche E-Mail-Adresse fehlt noch.",
                )
