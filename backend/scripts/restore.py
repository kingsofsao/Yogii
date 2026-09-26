"""Restore the Yogii database from a backup made by backend.scripts.backup.

    python -m backend.scripts.restore <backup-file> --yes

Restoring REPLACES the current data. Stop the API first, restore, then run
`alembic upgrade head` in case the backup is from an older schema.
"""

import argparse
import os
import shutil
import subprocess

from backend.core.config import settings


def restore_database(source: str) -> None:
    if not os.path.exists(source):
        raise SystemExit(f"Backup file not found: {source}")
    url = settings.DATABASE_URL
    if url.startswith("postgresql"):
        subprocess.run(["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-privileges",
                        "--single-transaction", "--dbname", url, source], check=True)
    elif url.startswith("sqlite"):
        shutil.copyfile(source, url.replace("sqlite:///", ""))
    else:
        raise SystemExit(f"Unsupported database URL scheme for restore: {url.split(':', 1)[0]}")
    print("Restore complete. Now run: alembic upgrade head")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("backup_file")
    ap.add_argument("--yes", action="store_true", help="confirm that current data will be replaced")
    args = ap.parse_args()
    if not args.yes:
        raise SystemExit("Restoring replaces the current database. Re-run with --yes to confirm.")
    restore_database(args.backup_file)
