"""Isolated browser fixture; never reads production secrets or databases."""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import uvicorn

    from server import admin_db, analytics

    directory = Path(os.environ["TGL_BROWSER_FIXTURE"])
    admin_db.DB_PATH = directory / "admin.db"
    analytics.KEY_PATH = directory / "analytics.key"
    os.environ["DATABASE_PATH"] = str(directory / "absent.db")
    os.environ["ADMIN_ORIGIN"] = "https://127.0.0.1:8795"
    from server import admin, ai_client, outreach
    import threading

    # Only this isolated fixture executes synthetic jobs immediately after a click.
    ai_client.configured = lambda: True
    ai_client.request = lambda *args, **kwargs: (
        {
            "should_draft": True,
            "subject": "A timely research conversation",
            "body": "Hello,\n\nyour research connects with our campaign. Could we exchange feedback?\n\nDaniel",
            "rationale": "Synthetischer Anlass für den Browsertest.",
            "framing": "research",
        },
        set(),
    )
    outreach.wake_worker = lambda: threading.Timer(0.3, outreach.process_one).start()

    if os.getenv("TGL_BROWSER_DIRECT_SEND") == "1":
        from server import outreach_delivery

        os.environ.update(
            OUTREACH_DIRECT_SEND_ENABLED="1",
            OUTREACH_SMTP_USER="sender@example.test",
            OUTREACH_SMTP_PASSWORD="synthetic-password",
            OUTREACH_FROM="sender@example.test",
            OUTREACH_REPLY_TO="reply@example.test",
        )
        outreach_delivery.submit = lambda row: ("sent", "Vom Testserver angenommen.")

        def archive_fixture(row):
            with admin_db.database() as db:
                db.execute(
                    "UPDATE outreach_deliveries SET archive_status='done' WHERE draft_id=?",
                    (row["draft_id"],),
                )
            return "done"

        outreach_delivery.archive = archive_fixture

    admin_db.ensure_schema()
    with admin_db.database() as db:
        db.execute(
            "INSERT INTO users(email,password_hash) VALUES (?,?)",
            (
                "browser@example.test",
                admin.password_hash.hash("synthetic-browser-password"),
            ),
        )
        db.execute(
            "INSERT INTO contacts(organization,email,permission,discovery_source,website,contact_url,created_at,updated_at) "
            "VALUES ('Synthetic partner','partner@example.test','existing','https://example.org/research','https://example.org/','https://example.org/contact',?,?)",
            (admin_db.now(), admin_db.now()),
        )
        db.execute(
            "INSERT INTO opportunities(contact_id,title,source_url,reason,cta,created_at,score,score_reason,kind,discovered_new) "
            "VALUES (1,'Synthetic research','https://example.org/research','A relevant topic','Exchange feedback',?,80,'Synthetic score','campaign',1)",
            (admin_db.now(),),
        )
    if os.getenv("TGL_BROWSER_THREAD") == "1":
        with admin_db.database() as db:
            db.execute(
                """INSERT INTO messages(contact_id,direction,message_id,subject,body,occurred_at,peer_addresses,references_json) VALUES (1,'inbound','<prior@example.test>','Existing conversation','Earlier feedback','2026-10-10','["partner@example.test"]','["<root@example.test>"]')"""
            )
    if os.getenv("TGL_BROWSER_QUALITY") == "1":
        from server import opportunity_quality as quality

        evidence = "We organize a visible exit from addictive social platforms."
        with admin_db.database() as db:
            for oid, title, fit, opening in [
                (1, "Weak match", 1, 0),
                (2, "Excellent match", 3, 3),
                (3, "Good match", 3, 2),
            ]:
                if oid == 1:
                    db.execute("UPDATE opportunities SET title=? WHERE id=1", (title,))
                else:
                    db.execute(
                        "INSERT INTO opportunities(contact_id,title,source_url,created_at) VALUES (1,?,'https://example.org/research',?)",
                        (title, admin_db.now()),
                    )
                quality.save(
                    db,
                    oid,
                    quality.Assessment(
                        fit=fit,
                        contact_fit=3,
                        opening_fit=opening,
                        reason="Synthetische Bewertung mit belegtem Bezug.",
                        startpoint="Können wir zu eurem Plattformausstieg beitragen?",
                        source_quote=evidence,
                    ),
                    evidence,
                )
                db.execute(
                    "INSERT INTO drafts(contact_id,opportunity_id,subject,body,created_at,updated_at) VALUES (1,?,?,'Synthetic draft',?,?)",
                    (oid, title, admin_db.now(), admin_db.now()),
                )
    uvicorn.run(
        admin.app,
        host="127.0.0.1",
        port=8795,
        access_log=False,
        ssl_keyfile=str(directory / "key.pem"),
        ssl_certfile=str(directory / "cert.pem"),
    )


if __name__ == "__main__":
    main()
