"""Smoke test: open every page and API endpoint and check none of them crash.

It does not check that the numbers are right, only that each URL still answers
(no 500 "Internal Server Error"). Run it before and after any big change:

    pip install -r requirements-dev.txt
    pytest -q

Needs a database built from schema.sql plus the dev seed
(.devcontainer/db-init/02-dev-seed.sql), with DATABASE_URL pointing at it.
The tests are skipped if no database can be reached.
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from psycopg2 import OperationalError

import main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # templates/ and static/ are found relative to the repo folder


try:
    from core.db import get_connection  # after main.py was split up
except ImportError:
    from main import get_connection  # before the split


def database_available() -> bool:
    try:
        get_connection().close()
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not database_available(), reason="no database reachable (set DATABASE_URL)"
)


def first_id(table: str, column: str):
    """An ID that exists in the database, so card/lineage pages have something
    to show.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT {column} FROM {table} ORDER BY {column} LIMIT 1")
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


PAGES = [
    "/",
    "/login",
    "/chart",
    "/graph",
    "/directory",
    "/inventory/materials",
    "/inventory/coatings",
    "/inventory/slp",
    "/inventory/coincell",
    "/inventory/mlp",
    "/inventory/materials/export",
    "/inventory/coatings/export?format=xlsx",
    "/materials/new",
    "/coatings/new",
    "/slp/new",
    "/coincell/new",
    "/mlp/new",
    "/materials/bulk-upload",
    "/coatings/bulk-upload",
    "/slp/bulk-upload",
    "/coincell/bulk-upload",
    "/mlp/bulk-upload",
    "/cycling/upload",
    "/HAZbot",
    "/admin/users/new",
    "/api/graph",
    "/api/filters",
    "/api/chart/formation-capacity",
    "/api/chart/my-projects",
    "/api/chart/gsm-by-coating",
    "/api/chart/records-per-table",
    "/api/chart/coatings-over-time",
]

RECORD_PAGES = [
    "/directory?record_id={id}",
    "/card/{id}",
    "/card/{id}/lineage",
    "/api/card/{id}",
    "/api/lineage/{id}",
    "/qr/{id}.png",
    "/api/graph/{id}",
]

RECORD_TABLES = [
    ("tbl_materials", "material_id"),
    ("tbl_coating", "coating_id"),
    ("tbl_slp", "slp_id"),
    ("tbl_coincell", "coincell_id"),
    ("tbl_mlp", "mlp_id"),
]


@pytest.fixture(scope="module")
def client():
    """A logged-in browser session (dev / dev from the dev seed)."""
    c = TestClient(main.app, follow_redirects=False)
    response = c.post("/login", data={"username": "dev", "password": "dev"})
    assert response.status_code == 303, "dev login failed - is the dev seed loaded?"
    return c


@pytest.mark.parametrize("path", PAGES)
def test_page_does_not_crash(client, path):
    assert client.get(path).status_code < 500


@pytest.mark.parametrize("table,column", RECORD_TABLES)
def test_record_pages_do_not_crash(client, table, column):
    record_id = first_id(table, column)
    if record_id is None:
        pytest.skip(f"{table} is empty")
    for template in RECORD_PAGES:
        path = template.format(id=record_id)
        assert client.get(path).status_code < 500, path


def test_unknown_id_is_404_not_500(client):
    assert client.get("/card/ZZZ-1").status_code == 404
    assert client.get("/api/card/ZZZ-1").status_code == 404
