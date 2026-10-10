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
    from server import admin

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
            "INSERT INTO contacts(organization,email,permission,created_at,updated_at) "
            "VALUES ('Synthetic partner','partner@example.test','existing',?,?)",
            (admin_db.now(), admin_db.now()),
        )
        db.execute(
            "INSERT INTO opportunities(contact_id,title,source_url,reason,cta,created_at,score,score_reason) "
            "VALUES (1,'Synthetic research','https://example.org/research','A relevant topic','Exchange feedback',?,80,'Synthetic score')",
            (admin_db.now(),),
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
