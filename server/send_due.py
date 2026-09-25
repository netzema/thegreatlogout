from __future__ import annotations

import fcntl
from pathlib import Path

from server.app import send_due_emails

LOCK_PATH = Path("/tmp/thegreatlogout-send-due.lock")


def main() -> None:
    with LOCK_PATH.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        sent = send_due_emails()
        print(f"Processed due guide emails: {sent}")


if __name__ == "__main__":
    main()
