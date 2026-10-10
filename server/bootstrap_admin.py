"""Explicit one-time imports. Source databases are opened read-only, never as an app."""

from __future__ import annotations

import argparse
import os
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from server import admin_db as storage
from server.analytics import KEY_PATH

MEDIA = [
    "profil",
    "Der Standard",
    "MOMENT",
    "Falter",
    "Kurier",
    "futurezone",
    "Die Presse",
    "Die ZEIT",
    "FM4",
    "Ö1",
    "Übermedien",
    "Krautreporter",
    "CORRECTIV",
]
NGOS = [
    "epicenter.works",
    "Saferinternet.at",
    "AlgorithmWatch",
    "noyb",
    "EDRi",
    "European Alternatives",
    "Corporate Europe Observatory",
    "People vs Big Tech",
]


def seed():
    storage.ensure_schema()
    if not KEY_PATH.exists():
        fd = os.open(KEY_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(secrets.token_bytes(32))
    with storage.database() as db:
        for name in MEDIA + NGOS:
            status = "no_response"
            notes = "Laut Daniel am 10.10.2026 angeschrieben, keine Antwort. Versanddaten und genaue Anzahl noch offen."
            if name in {"profil", "Der Standard", "MOMENT", "futurezone"}:
                notes = "Laut Daniel am 10.10.2026 mehrfach angeschrieben, keine Antwort. Genaue Anzahl und Versanddaten noch offen."
            if name == "European Alternatives":
                notes += " Zwei Einträge der Ausgangsliste gehören zu derselben Organisation."
            if name == "People vs Big Tech":
                status = "dialogue"
                notes = (
                    "Früherer Austausch mit Antwort. Daniel bedankte sich und kündigte eine Wiederaufnahme "
                    "nach dem September-Treffen an. Laut Daniel am 10.10.2026 seither keine weitere Nachricht "
                    "auf beiden Seiten. Kein neuer Versand bestätigt."
                )
            db.execute(
                """INSERT OR IGNORE INTO contacts
                (seed_key,organization,category,status,notes,next_step,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    "initial:" + name.lower(),
                    name,
                    "media" if name in MEDIA else "ngo",
                    status,
                    notes,
                    "Bisherigen Verlauf abgleichen und passenden nächsten Schritt prüfen.",
                    storage.now(),
                    storage.now(),
                ),
            )


def import_user(source):
    with sqlite3.connect(f"{Path(source).resolve().as_uri()}?mode=ro", uri=True) as db:
        users = db.execute(
            "SELECT email,password_hash FROM users WHERE is_active=1"
        ).fetchall()
    if len(users) != 1:
        raise RuntimeError(
            "Expected exactly one active source admin; select an account explicitly before migration"
        )
    with storage.database() as db:
        # Never overwrite a password after the admin has changed it independently.
        db.execute(
            "INSERT OR IGNORE INTO users(email,password_hash) VALUES (?,?)", users[0]
        )
    return 1


def import_analytics(source):
    cutoff = (
        (datetime.now(UTC) - timedelta(days=90)).replace(tzinfo=None).isoformat(sep=" ")
    )
    with sqlite3.connect(f"{Path(source).resolve().as_uri()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """SELECT * FROM analytics_events
            WHERE site IN ('thegreatlogout.org','www.thegreatlogout.org','api.thegreatlogout.org')
            AND occurred_at>=?""",
            (cutoff,),
        ).fetchall()
    imported = 0
    with storage.database() as db:
        for row in rows:
            fields = dict(row)
            fields.pop("id", None)
            dt = datetime.fromisoformat(fields["occurred_at"])
            fields["occurred_at"] = (
                (dt if dt.tzinfo else dt.replace(tzinfo=UTC))
                .astimezone(UTC)
                .isoformat()
            )
            cursor = db.execute(
                "INSERT OR IGNORE INTO analytics_events ("
                + ",".join(fields)
                + ") VALUES ("
                + ",".join("?" for _ in fields)
                + ")",
                list(fields.values()),
            )
            imported += cursor.rowcount
    return imported


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-source", type=Path)
    parser.add_argument("--analytics-source", type=Path)
    args = parser.parse_args()
    seed()
    if args.user_source:
        print("Admin accounts imported:", import_user(args.user_source))
    if args.analytics_source:
        print(
            "Campaign analytics events imported:",
            import_analytics(args.analytics_source),
        )


if __name__ == "__main__":
    main()
