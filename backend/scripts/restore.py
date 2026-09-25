import os
import sys
import subprocess

def restore_database(source_file: str):
    """
    Restores database from backup file.
    Supports PostgreSQL via psql and SQLite via direct restore.
    """
    if not os.path.exists(source_file):
        raise FileNotFoundError(f"Source backup file not found: {source_file}")

    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/yogii.db")

    if "postgres" in db_url:
        print(f"Restoring PostgreSQL database from {source_file}...")
        cmd = ["psql", db_url, "-f", source_file]
        subprocess.run(cmd, check=True)
        print("PostgreSQL restore complete.")
    elif "sqlite" in db_url:
        import shutil
        sqlite_file = db_url.replace("sqlite:///", "")
        shutil.copyfile(source_file, sqlite_file)
        print(f"SQLite restore complete to {sqlite_file}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m backend.scripts.restore <source_backup_file>")
        sys.exit(1)
    restore_database(sys.argv[1])
