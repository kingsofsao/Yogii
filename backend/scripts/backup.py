"""Back up the Yogii database.

    python -m backend.scripts.backup [output-path]

PostgreSQL: `pg_dump --format=custom` (restore with backend.scripts.restore).
SQLite: an online, consistent copy using SQLite's backup API.

Backups contain encrypted personal data and keyed hashes. They are only
useful together with YOGII_ENCRYPTION_KEY / YOGII_LOOKUP_HMAC_KEY, which must
be stored separately (never in the same place as the backup).
"""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

from backend.core.config import settings


def backup_database(output: str | None = None) -> str:
    url = settings.DATABASE_URL
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs("backups", exist_ok=True)
    if url.startswith("postgresql"):
        out = output or f"backups/yogii-{stamp}.dump"
        subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--file", out, url], check=True)
    elif url.startswith("sqlite"):
        out = output or f"backups/yogii-{stamp}.db"
        src = sqlite3.connect(url.replace("sqlite:///", ""))
        dst = sqlite3.connect(out)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
    else:
        raise SystemExit(f"Unsupported database URL scheme for backup: {url.split(':', 1)[0]}")
    os.chmod(out, 0o600)
    print(f"Backup written to {out} (permissions 600).")
    return out


if __name__ == "__main__":
    backup_database(sys.argv[1] if len(sys.argv) > 1 else None)
