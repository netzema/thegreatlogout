"""Reuse the owner's message assignments as address evidence, without sending."""

import json
import re

from server import admin_db as storage


def valid_address(value):
    return (
        isinstance(value, str)
        and len(value) <= 254
        and bool(re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+", value))
    )


def inherit_addresses(db):
    """Idempotent. Never overwrite a chosen address or unblock a contact."""
    changed = 0
    db.execute("DELETE FROM contact_address_issues")
    rows = db.execute(
        "SELECT * FROM messages WHERE matched=1 AND contact_id IS NOT NULL "
        "AND automated=0 ORDER BY occurred_at DESC,id DESC"
    ).fetchall()
    candidates = {}
    for row in rows:
        peers = [
            p.lower() for p in json.loads(row["peer_addresses"]) if valid_address(p)
        ]
        peers = [p for p in peers if p.rsplit("@", 1)[1] != "thegreatlogout.org"]
        if len(peers) != 1:
            if peers:
                db.execute(
                    "INSERT OR REPLACE INTO contact_address_issues VALUES (?,?)",
                    (
                        row["contact_id"],
                        "Mehrere Empfänger in einer Nachricht; beim Entwurf auswählen.",
                    ),
                )
            continue
        candidates.setdefault(row["contact_id"], []).append(
            (peers[0], row["direction"], row["id"])
        )
    owners = {}
    for cid, evidence in candidates.items():
        for address, _, _ in evidence:
            owners.setdefault(address, set()).add(cid)
    for cid, evidence in candidates.items():
        current = db.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        if db.execute(
            "SELECT 1 FROM outreach_deliveries s JOIN drafts d ON d.id=s.draft_id WHERE d.contact_id=? AND s.status IN ('sending','unknown')",
            (cid,),
        ).fetchone():
            continue
        usable = []
        for address, direction, mid in evidence:
            conflict = db.execute(
                "SELECT id FROM contacts WHERE lower(email)=? AND id!=? UNION "
                "SELECT contact_id FROM contact_addresses WHERE address=? AND contact_id!=?",
                (address, cid, address, cid),
            ).fetchone()
            if conflict or len(owners[address]) > 1:
                db.execute(
                    "INSERT OR REPLACE INTO contact_address_issues VALUES (?,?)",
                    (
                        cid,
                        "Adresse kommt bei mehreren Kontakten vor; im Review zuordnen.",
                    ),
                )
                continue
            db.execute(
                "INSERT OR IGNORE INTO contact_addresses VALUES (?,?,?,?)",
                (address, cid, f"assigned-message:{mid}", storage.now()),
            )
            usable.append((address, direction))
        outgoing = [address for address, direction in usable if direction == "outbound"]
        primary = current["email"] or (outgoing or [a for a, _ in usable] or [""])[0]
        permission = current["permission"]
        # 'existing' documents prior outreach; approval remains per draft.
        if permission == "unknown" and primary in outgoing:
            permission = "existing"
        if primary != current["email"] or permission != current["permission"]:
            db.execute(
                "UPDATE contacts SET email=?,permission=?,email_source=?,updated_at=? WHERE id=?",
                (
                    primary,
                    permission,
                    "Übernommen aus zugeordnetem Mailverlauf",
                    storage.now(),
                    cid,
                ),
            )
            db.execute(
                "UPDATE drafts SET status='draft',version=version+1,review_at=NULL "
                "WHERE contact_id=? AND status='approved'",
                (cid,),
            )
            changed += 1
    return changed


def main():
    storage.ensure_schema()
    with storage.database() as db:
        db.execute("BEGIN IMMEDIATE")
        print(f"Updated contacts: {inherit_addresses(db)}")


if __name__ == "__main__":
    main()
