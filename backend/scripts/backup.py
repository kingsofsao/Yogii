import os
import sys
import subprocess
from datetime import datetime, timezone

def backup_database(output_file: str = None):
    """
    Creates a database backup.
    Supports PostgreSQL via pg_dump and SQLite via direct file copy.
    """
    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/yogii.db")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = output_file or f"backup_yogii_{timestamp}.sql"

    if "postgres" in db_url:
        print(f"Executing PostgreSQL backup via pg_dump to {out}...")
        cmd = ["pg_dump", db_url, "-f", out]
        subprocess.run(cmd, check=True)
        print(f"PostgreSQL backup successfully written to {out}")
    elif "sqlite" in db_url:
        import shutil
        sqlite_file = db_url.replace("sqlite:///", "")
        dest = out.replace(".sql", ".db")
        shutil.copyfile(sqlite_file, dest)
        print(f"SQLite backup successfully created at {dest}")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    backup_database(target)
