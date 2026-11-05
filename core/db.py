import os
import psycopg2
from psycopg2 import sql

from core.varreg import settings


def connect(user, password, read_only):
    if password:
        conn = psycopg2.connect(host=settings.get("database", "host"), port=settings.get("database", "port"),
                                dbname=settings.get("database", "name"), user=user, password=password)
    else:
        conn = psycopg2.connect(dbname="bmac", user="hazma", host="localhost")
    if read_only:
        conn.set_session(readonly=True)
    return conn


def get_connection(read_only=False):
    if read_only:
        return connect("hazbat_ro", settings.get("database", "read_only_password"), True)
    return connect("hazbat_rw", settings.get("database", "read_write_password"), False)


def get_admin_connection():
    return connect("hazbat_admin", settings.get("database", "admin_password"), False)


def table_sequences(cur, table):
    """Names of the sequences owned by a table's columns."""
    cur.execute(
        "SELECT s.relname FROM pg_class s JOIN pg_depend d ON d.objid = s.oid "
        "JOIN pg_class t ON d.refobjid = t.oid WHERE s.relkind = 'S' AND t.relname = %s",
        (table,)
    )
    return [row[0] for row in cur.fetchall()]


def grant_privileges(cur, role, privileges, table):
    """Grants a role privileges on a table, and on its sequences if it can insert."""
    cur.execute(sql.SQL("GRANT {} ON {} TO {}").format(
        sql.SQL(privileges), sql.Identifier(table), sql.Identifier(role)))
    if "INSERT" in privileges:
        for sequence in table_sequences(cur, table):
            cur.execute(sql.SQL("GRANT USAGE ON SEQUENCE {} TO {}").format(
                sql.Identifier(sequence), sql.Identifier(role)))


def apply_schemas(conn, cur):
    """Runs each file in schemas/ that hasn't been applied yet, in name order, and records it."""
    cur.execute("CREATE TABLE IF NOT EXISTS tbl_schema_versions "
                "(filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    cur.execute("SELECT filename FROM tbl_schema_versions")
    applied = [row[0] for row in cur.fetchall()]
    directory = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schemas")
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".sql") or filename in applied:
            continue
        with open(os.path.join(directory, filename)) as f:
            cur.execute(f.read())
        cur.execute("INSERT INTO tbl_schema_versions (filename) VALUES (%s)", (filename,))
        conn.commit()


def setup_database():
    """Applies the files in schemas/ not yet applied, creates missing roles and grants them the tables in
    tbl_unprivileged_tables. Assumes the admin role exists."""
    roles = {"hazbat_rw": "read_write_password", "hazbat_ro": "read_only_password"}
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        apply_schemas(conn, cur)
        for role, variable in roles.items():
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cur.fetchone():
                continue
            password = settings.get("database", variable)
            if not password:
                raise RuntimeError(f"{variable} is not set")
            cur.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(sql.Identifier(role)), (password,))
        cur.execute("SELECT table_name FROM tbl_unprivileged_tables")
        unprivileged = [row[0] for row in cur.fetchall()]
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        privileged = [row[0] for row in cur.fetchall() if row[0] not in unprivileged]
        for table in privileged:
            cur.execute(sql.SQL("REVOKE ALL ON {} FROM {}").format(
                sql.Identifier(table), sql.SQL(", ").join(sql.Identifier(role) for role in roles)))
        for table in unprivileged:
            grant_privileges(cur, "hazbat_rw", "SELECT, INSERT, UPDATE, DELETE", table)
            grant_privileges(cur, "hazbat_ro", "SELECT", table)
        conn.commit()
    finally:
        cur.close()
        conn.close()
