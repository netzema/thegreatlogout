"""Encrypted, independently restorable campaign backups on an explicit rclone target."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile

from server import admin_db as storage
from server.maintenance import backup


class BackupError(Exception):
    pass


def run(args, timeout=180):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise BackupError(
            "Backup-Werkzeug nicht verfügbar oder Zeitlimit erreicht"
        ) from None
    if result.returncode:
        raise BackupError(
            "Backup-Schritt fehlgeschlagen; Zugriff und Konfiguration prüfen"
        )
    return result.stdout


def key_path():
    return storage.ROOT / "data" / "backup-recovery.key"


def ensure_key():
    path = key_path()
    if not path.exists():
        with open(path, "x", opener=lambda p, f: os.open(p, f, 0o600)) as f:
            f.write(secrets.token_urlsafe(48) + "\n")
    if path.stat().st_mode & 0o077:
        raise BackupError("Wiederherstellungsschlüssel muss Modus 600 haben")
    return path


def crypt(source, target, *, decrypt=False, key=None):
    args = [
        "gpg",
        "--batch",
        "--yes",
        "--pinentry-mode",
        "loopback",
        "--passphrase-file",
        str(key or ensure_key()),
        "--output",
        str(target),
    ]
    if decrypt:
        args += ["--decrypt", str(source)]
    else:
        args += ["--symmetric", "--cipher-algo", "AES256", str(source)]
    run(args)
    target.chmod(0o600)


def verify_archive(encrypted, *, key=None):
    """Decrypt and test in isolation; never overwrite live data."""
    with tempfile.TemporaryDirectory(
        prefix="tgl-restore-", dir=storage.ROOT / "data"
    ) as temp:
        directory = Path(temp)
        archive = directory / "restore.tar.gz"
        crypt(encrypted, archive, decrypt=True, key=key)
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            allowed = {
                "admin.db",
                "guide.db",
                "analytics.key",
                ".env",
                ".env.admin",
                "manifest.json",
            }
            if any(m.name not in allowed or not m.isfile() for m in members):
                raise BackupError("Unerwartete Dateien im Backup")
            manifest = json.load(bundle.extractfile("manifest.json"))
            if (
                not {"admin.db", "guide.db", "analytics.key", ".env", ".env.admin"}
                <= manifest.keys()
            ):
                raise BackupError("Backup ist unvollständig")
            for name, expected in manifest.items():
                data = bundle.extractfile(name).read()
                if hashlib.sha256(data).hexdigest() != expected:
                    raise BackupError("Backup-Prüfsumme stimmt nicht")
                target = directory / name
                target.write_bytes(data)
                target.chmod(0o600)
                if name.endswith(".db"):
                    with sqlite3.connect(f"{target.as_uri()}?mode=ro", uri=True) as db:
                        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise BackupError("Datenbankprüfung fehlgeschlagen")
        return len(manifest)


def create_and_upload():
    target = os.getenv("OUTREACH_BACKUP_REMOTE", "")
    # A dedicated absolute remote directory is required. Never write into its root.
    if (
        ":" not in target
        or not target.split(":", 1)[1].strip("/")
        or ".." in target.split("/")
    ):
        raise BackupError("Separates externes Backup-Ziel fehlt")
    data_dir = storage.ROOT / "data"
    ensure_key()
    stamp = storage.now().replace(":", "").replace("-", "").split(".")[0]
    with tempfile.TemporaryDirectory(prefix="tgl-backup-", dir=data_dir) as temp:
        directory = Path(temp)
        backup(storage.DB_PATH, directory / "admin.db")
        backup(
            Path(os.getenv("DATABASE_PATH", data_dir / "thegreatlogout.db")),
            directory / "guide.db",
        )
        for name, source in {
            "analytics.key": data_dir / "analytics.key",
            ".env": storage.ROOT / ".env",
            ".env.admin": storage.ROOT / ".env.admin",
        }.items():
            if not source.exists():
                raise BackupError("Erforderliche Wiederherstellungsdatei fehlt")
            shutil.copyfile(source, directory / name)
            (directory / name).chmod(0o600)
        manifest = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.iterdir()
        }
        (directory / "manifest.json").write_text(json.dumps(manifest))
        archive = directory / "campaign.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for name in [*manifest, "manifest.json"]:
                bundle.add(directory / name, arcname=name, recursive=False)
        encrypted = directory / f"campaign-{stamp}.tar.gz.gpg"
        crypt(archive, encrypted)
        remote_file = target.rstrip("/") + "/" + encrypted.name
        run(["rclone", "copyto", str(encrypted), remote_file], timeout=300)
        downloaded = directory / "downloaded.gpg"
        run(["rclone", "copyto", remote_file, str(downloaded)], timeout=300)
        if (
            hashlib.sha256(downloaded.read_bytes()).digest()
            != hashlib.sha256(encrypted.read_bytes()).digest()
        ):
            raise BackupError("Externes Backup stimmt nicht mit Original überein")
        verified = verify_archive(downloaded)
        # Retain only our archive prefix in the dedicated directory for 14 days.
        run(
            [
                "rclone",
                "delete",
                target,
                "--min-age",
                "14d",
                "--include",
                "campaign-*.tar.gz.gpg",
            ]
        )
        return verified


def main():
    os.umask(0o077)
    storage.ensure_schema()
    with (storage.ROOT / "data" / "offsite-backup.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            count, status = create_and_upload(), "ok"
        except (BackupError, OSError, sqlite3.Error, tarfile.TarError, ValueError):
            count, status = 0, "failed"
        with storage.database() as db:
            db.execute(
                "INSERT OR REPLACE INTO job_runs VALUES ('offsite_backup',?,?,?)",
                (storage.now(), status, count),
            )
        if status != "ok":
            raise SystemExit(
                "External backup failed; inspect configuration (no secrets logged)."
            )


if __name__ == "__main__":
    main()
