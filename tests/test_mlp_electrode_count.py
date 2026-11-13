"""MLP cathode / anode counts (tbl_mlp.cathode_count, tbl_mlp.anode_count).

Checks the database rules: cathode_count defaults to 1, must be 1-100, and
anode_count is always cathode_count + 1. Each test runs in a transaction that
is rolled back, so no rows are left behind. Skipped if no database is reachable.

pytest -q tests/test_mlp_electrode_count.py
"""

import os
import sys
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import OperationalError

from core.db import get_connection

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

CATHODE_MATERIAL = "CAT-TEST-ELEC-001"
ANODE_MATERIAL = "AN-TEST-ELEC-001"
CATHODE_COATING = "CAT-TEST-ELEC-001-C001"
ANODE_COATING = "AN-TEST-ELEC-001-C001"
MLP_ID = "MLP-TEST-ELEC-0001"


def database_available() -> bool:
    try:
        get_connection().close()
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not database_available(), reason="no database reachable"
)


@pytest.fixture
def cur():
    """A cursor with a throwaway cathode and anode coating. Everything is rolled
    back afterwards.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO tbl_materials (material_id) VALUES (%s), (%s)",
            (CATHODE_MATERIAL, ANODE_MATERIAL),
        )
        cursor.execute(
            "INSERT INTO tbl_coating (coating_id, material_id) "
            "VALUES (%s, %s), (%s, %s)",
            (CATHODE_COATING, CATHODE_MATERIAL, ANODE_COATING, ANODE_MATERIAL),
        )
        yield cursor
    finally:
        conn.rollback()
        cursor.close()
        conn.close()


def insert_mlp(cur, cathode_count=None):
    """Insert the test MLP and return (cathode_count, anode_count). Leaves
    cathode_count out when it is None, so the column default applies.
    """
    if cathode_count is None:
        cur.execute(
            "INSERT INTO tbl_mlp (mlp_id, cat_coating_id, an_coating_id) "
            "VALUES (%s, %s, %s) RETURNING cathode_count, anode_count",
            (MLP_ID, CATHODE_COATING, ANODE_COATING),
        )
    else:
        cur.execute(
            "INSERT INTO tbl_mlp (mlp_id, cat_coating_id, an_coating_id, "
            "cathode_count) VALUES (%s, %s, %s, %s) "
            "RETURNING cathode_count, anode_count",
            (MLP_ID, CATHODE_COATING, ANODE_COATING, cathode_count),
        )
    return cur.fetchone()


def test_default_is_one(cur):
    assert insert_mlp(cur) == (1, 2)


@pytest.mark.parametrize("cathodes", [1, 7, 100])
def test_anode_is_cathode_plus_one(cur, cathodes):
    assert insert_mlp(cur, cathodes) == (cathodes, cathodes + 1)


def test_anode_follows_update(cur):
    insert_mlp(cur)
    cur.execute(
        "UPDATE tbl_mlp SET cathode_count = %s WHERE mlp_id = %s "
        "RETURNING cathode_count, anode_count",
        (4, MLP_ID),
    )
    assert cur.fetchone() == (4, 5)


@pytest.mark.parametrize("cathodes", [0, 101])
def test_out_of_range_rejected(cur, cathodes):
    with pytest.raises(psycopg2.errors.CheckViolation):
        insert_mlp(cur, cathodes)


def test_null_rejected(cur):
    with pytest.raises(psycopg2.errors.NotNullViolation):
        cur.execute(
            "INSERT INTO tbl_mlp (mlp_id, cat_coating_id, an_coating_id, "
            "cathode_count) VALUES (%s, %s, %s, NULL)",
            (MLP_ID, CATHODE_COATING, ANODE_COATING),
        )


def test_anode_cannot_be_set(cur):
    with pytest.raises(psycopg2.errors.GeneratedAlways):
        cur.execute(
            "INSERT INTO tbl_mlp (mlp_id, cat_coating_id, an_coating_id, "
            "anode_count) VALUES (%s, %s, %s, %s)",
            (MLP_ID, CATHODE_COATING, ANODE_COATING, 5),
        )
