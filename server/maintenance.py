"""Campaign-owned retention and consistent SQLite backups."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from server import admin_db as storage
from server.analytics import prune


def backup(source, target):
    source, target = Path(source), Path(target)
    if not source.exists():
        raise FileNotFoundError("Required campaign database missing")
    with (
        closing(
            sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
        ) as original,
        closing(sqlite3.connect(target)) as copy,
    ):
        original.backup(copy)
        if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup integrity check failed")
    target.chmod(0o600)


def main():
    os.umask(0o077)
    storage.ensure_schema()
    prune()
    directory = storage.ROOT / "data" / "backups"
    directory.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    backup(storage.DB_PATH, directory / f"admin-{stamp}.db")
    backup(
        Path(os.getenv("DATABASE_PATH", storage.ROOT / "data" / "thegreatlogout.db")),
        directory / f"guide-{stamp}.db",
    )
    cutoff = datetime.now(UTC) - timedelta(days=14)
    for path in directory.glob("*.db"):
        # Prune expired analytics in retained admin snapshots too.
        if path.name.startswith("admin-"):
            with sqlite3.connect(path) as db:
                db.execute(
                    "DELETE FROM analytics_events WHERE occurred_at < ?",
                    ((datetime.now(UTC) - timedelta(days=90)).isoformat(),),
                )
                db.commit()
                db.execute("VACUUM")
        if (
            datetime.strptime(path.stem.split("-", 1)[1], "%Y%m%dT%H%M%S").replace(
                tzinfo=UTC
            )
            < cutoff
        ):
            path.unlink()
    with storage.database() as db:
        db.execute(
            "INSERT OR REPLACE INTO job_runs VALUES (?,?,?,?)",
            ("backup_and_retention", storage.now(), "ok", 2),
        )


if __name__ == "__main__":
    main()
