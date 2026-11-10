#!/usr/bin/env python3
# Adds any missing [app] settings to the config file. With the built-in
# database (START_LOCAL_DB) it also adds the missing database settings and
# role passwords, and sets up the admin role. dbgen.py creates the other two
# roles.
#   python3 -m scripts.initconfig   (from /app)

import os
import secrets
import string

import psycopg2
from psycopg2 import sql

from utils.config import ConfigFile, truthy


def config_path():
    return "/etc/hazbat/hazbat.ini"


def generate_password():
    """A random 32-character password of letters and digits."""
    alphabet = string.ascii_letters + string.digits
    characters = []
    for _ in range(32):
        characters.append(secrets.choice(alphabet))
    return "".join(characters)


def add_if_missing(config, section, name, value):
    """Sets a setting only if it is not in the file yet. Returns True if it
    was added.
    """
    if config.get(section, name) is not None:
        return False
    config.set(section, name, value)
    return True


def add_missing_database(config):
    """Adds anything missing from the [database] section. Returns True if
    anything was added.
    """
    added = False
    for name, value in (("host", "localhost"), ("port", "5432"), ("name", "bmac")):
        if add_if_missing(config, "database", name, value):
            added = True
    for name in ("admin_password", "read_write_password", "read_only_password"):
        if add_if_missing(config, "database", name, generate_password()):
            added = True
    return added


def add_missing_app(config):
    """Adds anything missing from the [app] section. Returns True if anything was added.
    The base URL is for testing only; replace it for any real use."""
    added = False
    for name, value in (
        ("base_url", "http://localhost:8000"),
        ("max_2fa_interval_hours", "48"),
        ("session_secret", generate_password()),
        ("two_factor_key", generate_password()),
    ):
        if add_if_missing(config, "app", name, value):
            added = True
    if truthy(os.getenv("NO_2FA")) and add_if_missing(
        config, "app", "disable_2fa", "true"
    ):
        added = True
    return added


def set_up_admin_role(password):
    """Creates the admin role if it does not exist, and lets it create tables
    in the schema.
    An existing role keeps its password."""
    role = "hazbat_admin"
    conn = psycopg2.connect(dbname="bmac", user="postgres", host="/run/postgresql")
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cur.fetchone() is None:
            cur.execute(
                sql.SQL("CREATE ROLE {} LOGIN CREATEROLE PASSWORD %s").format(
                    sql.Identifier(role)
                ),
                (password,),
            )
        cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        cur.execute(
            sql.SQL("GRANT ALL ON SCHEMA public TO {}").format(sql.Identifier(role))
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def main():
    path = config_path()
    config = ConfigFile.load(path)
    changed = add_missing_app(config)
    local = os.getenv("START_LOCAL_DB")
    if local and add_missing_database(config):
        changed = True
    if changed:
        config.save(path, 0o640, "app")
    if local:
        set_up_admin_role(config.get("database", "admin_password"))


if __name__ == "__main__":
    main()
