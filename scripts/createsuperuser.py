#!/usr/bin/env python3
# Create an admin user in tbl_users, prompting for the full name and password.
# If the user already exists it is replaced completely, after a confirmation.
#   createsuperuser [username]

import getpass
import sys

from core.db import get_admin_connection
from services.account import hash_password


def user_exists(username):
    """True if there is already a user with this name."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM tbl_users WHERE username = %s", (username,))
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else input("Username: ").strip()
    if not username:
        sys.exit("Username must not be empty")

    replacing = user_exists(username)
    if replacing:
        print(f"WARNING: user '{username}' already exists. Replacing it deletes that user completely, "
              "including their API keys, two-factor setup and project access, and creates a new administrator "
              "with the details you enter now.")
        if input("Replace it? [y/N]: ").strip().lower() != "y":
            sys.exit("Cancelled")

    full_name = input("Full name [admin]: ").strip()
    if not full_name:
        full_name = "admin"

    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Password (again): "):
        sys.exit("Passwords do not match")
    if not password:
        sys.exit("Password must not be empty")
    if len(password.encode()) > 72:
        sys.exit("Password must be at most 72 bytes (bcrypt limit)")

    password_hash = hash_password(password)

    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        # The foreign keys delete the old user's projects, API keys and two-factor data with it
        cur.execute("DELETE FROM tbl_users WHERE username = %s", (username,))
        cur.execute(
            "INSERT INTO tbl_users (username, password_hash, full_name, is_admin) VALUES (%s, %s, %s, TRUE)",
            (username, password_hash, full_name)
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    if replacing:
        print(f"Replaced user '{username}' with a new admin user")
    else:
        print(f"Created admin user '{username}'")


if __name__ == "__main__":
    main()
