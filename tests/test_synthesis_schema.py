"""Schema checks for tbl_material_synthesis_step. Needs a database; skipped if
none can be reached. Each test rolls back, so nothing is left behind.

pytest -q tests/test_synthesis_schema.py
"""

import os
import sys
from pathlib import Path

import pytest
from psycopg2 import OperationalError, errors

from core.db import get_connection

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

TEST_MATERIAL = "TEST-SYNTH-1"


def database_available() -> bool:
    try:
        get_connection().close()
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not database_available(), reason="no database reachable (set DATABASE_URL)"
)


@pytest.fixture
def cur():
    """A cursor with a test material inserted. Rolled back afterwards."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tbl_materials (material_id) VALUES (%s)", (TEST_MATERIAL,)
    )
    yield cursor
    conn.rollback()
    cursor.close()
    conn.close()


def insert_step(cur, step_no=1, duration_h=None):
    cur.execute(
        "INSERT INTO tbl_material_synthesis_step "
        "(material_id, step_no, step_type, duration_h) VALUES (%s, %s, %s, %s)",
        (TEST_MATERIAL, step_no, "calcination", duration_h),
    )


def test_table_exists(cur):
    cur.execute("SELECT to_regclass('tbl_material_synthesis_step')")
    assert cur.fetchone()[0] is not None


def test_valid_row_inserts(cur):
    cur.execute(
        "INSERT INTO tbl_material_synthesis_step "
        "(material_id, step_no, step_type, temperature_c, duration_h, atmosphere, "
        "equipment, notes, performed_by, performed_on) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING step_id",
        (
            TEST_MATERIAL,
            1,
            "calcination",
            900,
            12,
            "O2",
            "Tube furnace",
            "Ramp 5 C/min",
            "dev",
            "2026-11-12",
        ),
    )
    assert cur.fetchone()[0] is not None


def test_duplicate_step_no_rejected(cur):
    insert_step(cur, step_no=1)
    with pytest.raises(errors.UniqueViolation):
        insert_step(cur, step_no=1)


def test_step_no_zero_rejected(cur):
    with pytest.raises(errors.CheckViolation):
        insert_step(cur, step_no=0)


def test_negative_duration_rejected(cur):
    with pytest.raises(errors.CheckViolation):
        insert_step(cur, duration_h=-1)
