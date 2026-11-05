"""User management for admins: listing, locking, deleting and editing users. Tables: tbl_users and tbl_user_projects.

A user's own account is in services/account.py, API keys in services/api.py and two-factor in services/two_factor.py.
"""

from core.db import get_admin_connection


def list_users():
    """Every user, as a list of {user_id, username, full_name, is_admin, locked, projects, twofa_enabled}."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT u.user_id, u.username, u.full_name, u.is_admin, u.locked, "
            "COALESCE((SELECT array_agg(p.project_name ORDER BY p.project_name) FROM tbl_user_projects p "
            "WHERE p.user_id = u.user_id), '{}'), "
            "EXISTS (SELECT 1 FROM tbl_user_2fa t WHERE t.user_id = u.user_id AND t.confirmed_at IS NOT NULL) "
            "FROM tbl_users u ORDER BY lower(u.username)"
        )
        columns = ["user_id", "username", "full_name", "is_admin", "locked", "projects", "twofa_enabled"]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def set_user_locked(user_id, locked):
    """Locks or unlocks a user. A locked user cannot log in, and their sessions and API keys stop working."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE tbl_users SET locked = %s WHERE user_id = %s", (locked, user_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()


def delete_user(user_id):
    """Deletes a user and, through the foreign keys, their projects, API keys and two-factor data.
    Returns False if there is no such user."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM tbl_users WHERE user_id = %s RETURNING user_id", (user_id,))
        deleted = cur.fetchone() is not None
        conn.commit()
        return deleted
    finally:
        cur.close()
        conn.close()


def get_user_for_edit(user_id):
    """What the edit page shows: {user_id, username, full_name, is_admin, locked, twofa_enabled,
    projects (the user's), all_projects (every project that can be ticked)}. None if there is no such user."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT username, full_name, is_admin, locked FROM tbl_users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute("SELECT project_name FROM tbl_user_projects WHERE user_id = %s ORDER BY project_name", (user_id,))
        assigned = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT project_name FROM tbl_projects WHERE active = true")
        active = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM tbl_user_2fa WHERE user_id = %s AND confirmed_at IS NOT NULL)", (user_id,)
        )
        twofa_enabled = cur.fetchone()[0]
        # A project the user already has stays tickable even if it has since been made inactive
        return {"user_id": user_id, "username": row[0], "full_name": row[1], "is_admin": row[2], "locked": row[3],
                "twofa_enabled": twofa_enabled, "projects": assigned, "all_projects": sorted(set(active) | set(assigned))}
    finally:
        cur.close()
        conn.close()


def update_user(user_id, full_name, is_admin, projects):
    """Saves a user's full name, admin flag and project list together, or none of them."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE tbl_users SET full_name = %s, is_admin = %s WHERE user_id = %s", (full_name, is_admin, user_id))
        cur.execute("DELETE FROM tbl_user_projects WHERE user_id = %s", (user_id,))
        for project in projects:
            cur.execute("INSERT INTO tbl_user_projects (user_id, project_name) VALUES (%s, %s)", (user_id, project))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


