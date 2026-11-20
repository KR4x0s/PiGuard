"""Local dashboard accounts. Passwords and bootstrap secrets never travel in argv."""
import argparse
import getpass
import re
import time

from werkzeug.security import check_password_hash, generate_password_hash

from piguard.storage import connect


def set_user(db, username, password, role):
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{2,31}", username):
        raise ValueError("Username must be 3–32 ordinary characters.")
    if role not in {"admin", "viewer"} or len(password) < 14:
        raise ValueError("Choose admin/viewer and a password of at least 14 characters.")
    with db:
        db.execute("""INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)
          ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash,role=excluded.role""",
          (username, generate_password_hash(password, method="scrypt"), role, time.time()))


def authenticate(db, username, password):
    row = db.execute("SELECT id,username,password_hash,role FROM users WHERE username=?", (username,)).fetchone()
    if row and check_password_hash(row["password_hash"], password):
        return {"id": row["id"], "username": row["username"], "role": row["role"]}
    return None


def main():
    parser = argparse.ArgumentParser(description="Create or update a PiGuard dashboard account")
    parser.add_argument("--state", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", required=True, choices=("admin", "viewer"))
    args = parser.parse_args()
    password = getpass.getpass("New password (14+ characters): ")
    if password != getpass.getpass("Repeat password: "):
        parser.error("Passwords differ")
    with connect(args.state) as db:
        set_user(db, args.username, password, args.role)
    print("Account saved")


if __name__ == "__main__":
    main()
