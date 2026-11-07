"""Projects: listing them, creating one, and switching one on or off.

Tables: tbl_projects, and the record tables and tbl_user_projects for the counts shown beside each project.
"""

import re

import psycopg2

from core.db import get_admin_connection

# Names appear in URLs and in page scripts, so they are kept to plain characters
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,59}")

PROJECT_QUERY = (
    "SELECT p.project_name, p.active, "
    "(SELECT COUNT(*) FROM tbl_coating c WHERE c.project = p.project_name) "
    "+ (SELECT COUNT(*) FROM tbl_slp s WHERE s.project = p.project_name) "
    "+ (SELECT COUNT(*) FROM tbl_coincell cc WHERE cc.project = p.project_name) "
    "+ (SELECT COUNT(*) FROM tbl_mlp m WHERE m.project = p.project_name), "
    "(SELECT COUNT(*) FROM tbl_user_projects u WHERE u.project_name = p.project_name) "
    "FROM tbl_projects p"
)
PROJECT_COLUMNS = ["name", "active", "records", "users"]


def check_project_name(name):
    """An error message if the name cannot be used, otherwise None."""
    if not NAME_PATTERN.fullmatch(name):
        return ("A project name must start with a letter or a digit, use only letters, digits, spaces, dots, "
                "hyphens and underscores, and be at most 60 characters long.")
    return None


def list_projects():
    """Every project, as a list of {name, active, records, users}."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute(PROJECT_QUERY + " ORDER BY lower(p.project_name)")
        return [dict(zip(PROJECT_COLUMNS, row)) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def get_project(name):
    """One project as {name, active, records, users}, or None if there is no such project."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute(PROJECT_QUERY + " WHERE p.project_name = %s", (name,))
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip(PROJECT_COLUMNS, row))
    finally:
        cur.close()
        conn.close()


def create_project(name):
    """Creates an active project. Returns None on success or an error message.
    Names that differ only in capitals are treated as the same name."""
    error = check_project_name(name)
    if error:
        return error
    exists = "A project with that name already exists (names are compared ignoring capitals)."
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM tbl_projects WHERE lower(project_name) = lower(%s)", (name,))
        if cur.fetchone() is not None:
            return exists
        cur.execute("INSERT INTO tbl_projects (project_name, active) VALUES (%s, TRUE)", (name,))
        conn.commit()
        return None
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return exists
    finally:
        cur.close()
        conn.close()


def set_project_active(name, active):
    """Switches a project on or off. Returns False if there is no such project."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE tbl_projects SET active = %s WHERE project_name = %s RETURNING project_name", (active, name))
        found = cur.fetchone() is not None
        conn.commit()
        return found
    finally:
        cur.close()
        conn.close()
