"""Shared reply selection and RFC 5322 thread headers for SMTP and exports."""

import json
import re


MESSAGE_ID = re.compile(r"<[\x21-\x3b\x3d\x3f-\x7e]+@[\x21-\x3b\x3d\x3f-\x7e]+>")


def valid_id(value):
    return (
        isinstance(value, str)
        and len(value) <= 900
        and bool(MESSAGE_ID.fullmatch(value))
    )


def json_list(value):
    try:
        result = json.loads(value or "[]")
    except (ValueError, TypeError):
        return []
    return result if isinstance(result, list) else []


def choices(db, cid):
    return [
        row
        for row in db.execute(
            "SELECT * FROM messages WHERE contact_id=? AND automated=0 ORDER BY occurred_at DESC,id DESC",
            (cid,),
        )
        if valid_id(row["message_id"])
    ]


def matches_recipient(row, recipient):
    peers = json_list(row["peer_addresses"])
    return (
        not peers
        or not recipient
        or recipient.lower() in [str(p).lower() for p in peers]
    )


def latest(db, cid, recipient):
    return next(
        (row for row in choices(db, cid) if matches_recipient(row, recipient)), None
    )


def selected(db, cid, reply_id):
    if not reply_id:
        return None
    row = db.execute(
        "SELECT * FROM messages WHERE id=? AND contact_id=? AND automated=0",
        (reply_id, cid),
    ).fetchone()
    if row is None or not valid_id(row["message_id"]):
        raise ValueError(
            "Antwortbezug nicht mehr verfügbar. Bitte eine Unterhaltung im Entwurf auswählen."
        )
    return row


def subject(previous):
    title = " ".join(previous["subject"].split()).strip()
    if not title:
        return "Re:"
    if re.match(r"^(re|aw|sv):", title, re.IGNORECASE) or len(title) > 196:
        return title
    return "Re: " + title


def references(db, previous, seen=None):
    seen = set() if seen is None else seen
    mid = previous["message_id"]
    if mid in seen or len(seen) >= 30:
        return []
    seen.add(mid)
    refs = [r for r in json_list(previous["references_json"]) if valid_id(r)]
    parent_id = previous["in_reply_to"]
    if not refs and valid_id(parent_id):
        parent = db.execute(
            "SELECT * FROM messages WHERE message_id=? AND contact_id=?",
            (parent_id, previous["contact_id"]),
        ).fetchone()
        refs = references(db, parent, seen) if parent else [parent_id]
    refs = list(dict.fromkeys([r for r in refs if r != mid] + [mid]))
    # Keep the root and recent links; avoid unbounded headers from imported mail.
    return refs if len(refs) <= 30 else refs[:1] + refs[-29:]


def headers(db, draft):
    previous = selected(db, draft["contact_id"], draft["reply_message_id"])
    if previous is None:
        return {}
    return {
        "In-Reply-To": previous["message_id"],
        "References": " ".join(references(db, previous)),
    }


def apply_headers(db, message, draft):
    for key, value in headers(db, draft).items():
        message[key] = value
