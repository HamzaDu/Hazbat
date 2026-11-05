#!/usr/bin/env python3
# Sets the database up: loads the schema, creates the roles and grants their privileges.
#   python3 -m scripts.dbgen   (from /app)

from core.db import setup_database
from core.varreg import settings


def main():
    settings.require("database", "admin_password", "read_write_password", "read_only_password")
    setup_database()


if __name__ == "__main__":
    main()
