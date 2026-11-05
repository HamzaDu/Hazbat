"""The user's own account: passwords, name, what the My Account page and the session need, and whether any user exists.

Tables: tbl_users, and tbl_user_projects and tbl_user_2fa for reading.
"""

import bcrypt

from core.db import get_admin_connection


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def has_users():
    """True if tbl_users has at least one row."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT EXISTS (SELECT 1 FROM tbl_users)")
        return cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()


def get_login_details(user_id):
    """(full_name, is_admin, project names) for a user."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT full_name, is_admin FROM tbl_users WHERE user_id = %s", (user_id,))
        full_name, is_admin = cur.fetchone()
        cur.execute("SELECT project_name FROM tbl_user_projects WHERE user_id = %s", (user_id,))
        return full_name, is_admin, [row[0] for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def get_session_state(user_id):
    """(full_name, is_admin, project names) for a user whose session may continue,
    or None if the user has been deleted or locked."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT full_name, is_admin, locked FROM tbl_users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if row is None or row[2]:
            return None
        cur.execute("SELECT project_name FROM tbl_user_projects WHERE user_id = %s", (user_id,))
        return row[0], row[1], [r[0] for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def get_user_info(user_id):
    """What the My Account page shows: {username, full_name, is_admin, projects, twofa_enabled, twofa_last_used,
    twofa_interval_hours}."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT username, full_name, is_admin, EXTRACT(EPOCH FROM twofa_interval) FROM tbl_users WHERE user_id = %s",
            (user_id,)
        )
        username, full_name, is_admin, interval_seconds = cur.fetchone()
        cur.execute("SELECT project_name FROM tbl_user_projects WHERE user_id = %s ORDER BY project_name", (user_id,))
        projects = [row[0] for row in cur.fetchall()]
        cur.execute(
            "SELECT COUNT(*), MAX(last_used_at) FROM tbl_user_2fa WHERE user_id = %s AND confirmed_at IS NOT NULL",
            (user_id,)
        )
        methods, last_used = cur.fetchone()
        return {"username": username, "full_name": full_name, "is_admin": is_admin, "projects": projects,
                "twofa_enabled": methods > 0, "twofa_last_used": last_used,
                "twofa_interval_hours": int(interval_seconds) // 3600}
    finally:
        cur.close()
        conn.close()


def verify_user_password(user_id, password):
    """True if the password is the user's current one."""
    if len(password.encode()) > 72:
        return False  # longer than bcrypt can hold, so it cannot be a stored password
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT password_hash FROM tbl_users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        return row is not None and check_password(password, row[0])
    finally:
        cur.close()
        conn.close()


def set_user_password(user_id, password):
    """Stores a new password for the user. The caller has already checked the old one."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE tbl_users SET password_hash = %s WHERE user_id = %s", (hash_password(password), user_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()


def set_user_full_name(user_id, full_name):
    """Stores a new full name for the user."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE tbl_users SET full_name = %s WHERE user_id = %s", (full_name, user_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()
