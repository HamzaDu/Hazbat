"""API keys: creating, listing and revoking them, and finding the user behind a key. Table: tbl_api_keys.

Only a hash of each key is stored, so a key cannot be shown again after it is created.
"""

import hashlib
import secrets

from core.db import get_admin_connection


def hash_api_key(api_key):
    return hashlib.sha256(api_key.encode()).hexdigest()


def get_api_key_user(api_key):
    """Returns {"user_id", "is_admin", "projects"} for a valid API key, or None."""
    key_hash = hash_api_key(api_key)
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE tbl_api_keys SET last_used_at = now() "
            "WHERE key_hash = %s AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now()) "
            "RETURNING user_id",
            (key_hash,)
        )
        row = cur.fetchone()
        if not row:
            return None
        user_id = row[0]
        cur.execute("SELECT is_admin, locked FROM tbl_users WHERE user_id = %s", (user_id,))
        is_admin, locked = cur.fetchone()
        if locked:
            return None
        cur.execute("SELECT project_name FROM tbl_user_projects WHERE user_id = %s", (user_id,))
        projects = [r[0] for r in cur.fetchall()]
        conn.commit()
        return {"user_id": user_id, "is_admin": is_admin, "projects": projects}
    finally:
        cur.close()
        conn.close()


def create_api_key(user_id, name, expires_on=None):
    """Creates a key for the user and returns it. Only its hash is stored, so it cannot be shown again.
    expires_on is a date (the key works through that day) or None for a key that never expires."""
    api_key = secrets.token_urlsafe(32)
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO tbl_api_keys (user_id, name, key_hash, expires_at) "
            "VALUES (%s, %s, %s, (%s::date + 1)::timestamptz)",
            (user_id, name, hash_api_key(api_key), expires_on)
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return api_key


def list_api_keys(user_id):
    """The user's keys, newest first, each with a status of Active, Expired or Revoked."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT key_id, name, created_at, last_used_at, expires_at, "
            "CASE WHEN revoked_at IS NOT NULL THEN 'Revoked' "
            "WHEN expires_at IS NOT NULL AND expires_at <= now() THEN 'Expired' "
            "ELSE 'Active' END "
            "FROM tbl_api_keys WHERE user_id = %s ORDER BY created_at DESC, key_id DESC",
            (user_id,)
        )
        columns = ["key_id", "name", "created_at", "last_used_at", "expires_at", "status"]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def revoke_api_key(user_id, key_id):
    """Revokes one of the user's keys. Returns False if there is no such active key."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE tbl_api_keys SET revoked_at = now() "
            "WHERE key_id = %s AND user_id = %s AND revoked_at IS NULL RETURNING key_id",
            (key_id, user_id)
        )
        row = cur.fetchone()
        conn.commit()
        return row is not None
    finally:
        cur.close()
        conn.close()
