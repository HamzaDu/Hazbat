"""Synthesis step logic (services/synthesis.py).

The clean_step tests need no database. The others need one and are skipped if
none can be reached; they commit, so a fixture deletes the test material
afterwards (its steps go with it).

pytest -q tests/test_synthesis.py
"""

import os
import sys
from datetime import date
from pathlib import Path

import pytest
from psycopg2 import OperationalError

from core.db import get_connection
from services.synthesis import (
    SynthesisError,
    add_step,
    clean_step,
    delete_step,
    get_step,
    list_steps,
    update_step,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

TEST_MATERIAL = "TEST-SYNTH-2"


def database_available() -> bool:
    try:
        get_connection().close()
        return True
    except OperationalError:
        return False


needs_database = pytest.mark.skipif(
    not database_available(), reason="no database reachable (set DATABASE_URL)"
)


# --- clean_step (no database) ---------------------------------------------------


def test_clean_step_accepts_full_step():
    step = clean_step(
        {
            "step_no": "2",
            "step_type": " calcination ",
            "temperature_c": "900",
            "duration_h": "12.5",
            "atmosphere": "O2",
            "equipment": "Tube furnace",
            "notes": "Ramp 5 C/min",
            "performed_by": "dev",
            "performed_on": "2026-11-12",
        }
    )
    assert step["step_no"] == 2
    assert step["step_type"] == "calcination"
    assert step["temperature_c"] == 900.0
    assert step["duration_h"] == 12.5
    assert step["performed_on"] == date(2026, 11, 12)


def test_clean_step_blank_optional_fields_become_none():
    step = clean_step({"step_type": "mixing", "temperature_c": " ", "notes": ""})
    assert step["step_no"] is None
    assert step["temperature_c"] is None
    assert step["notes"] is None


def test_clean_step_accepts_json_numbers():
    step = clean_step({"step_type": "drying", "step_no": 3, "duration_h": 4})
    assert step["step_no"] == 3
    assert step["duration_h"] == 4.0


def test_clean_step_ignores_other_keys():
    step = clean_step({"step_type": "mixing", "step_id": 99, "material_id": "X"})
    assert "step_id" not in step
    assert "material_id" not in step


@pytest.mark.parametrize(
    "values",
    [
        pytest.param({}, id="no-step-type"),
        pytest.param({"step_type": "  "}, id="blank-step-type"),
        pytest.param({"step_type": "mixing", "step_no": "0"}, id="step-no-0"),
        pytest.param({"step_type": "mixing", "step_no": "-1"}, id="step-no-negative"),
        pytest.param({"step_type": "mixing", "step_no": "1.5"}, id="step-no-decimal"),
        pytest.param({"step_type": "mixing", "step_no": "abc"}, id="step-no-text"),
        pytest.param({"step_type": "mixing", "temperature_c": "-300"}, id="too-cold"),
        pytest.param({"step_type": "mixing", "temperature_c": "2500"}, id="too-hot"),
        pytest.param({"step_type": "mixing", "temperature_c": "hot"}, id="temp-text"),
        pytest.param({"step_type": "mixing", "duration_h": "0"}, id="duration-0"),
        pytest.param({"step_type": "mixing", "duration_h": "-2"}, id="duration-neg"),
        pytest.param({"step_type": "mixing", "duration_h": "inf"}, id="duration-inf"),
        pytest.param({"step_type": "mixing", "duration_h": "nan"}, id="duration-nan"),
        pytest.param(
            {"step_type": "mixing", "performed_on": "12/11/2026"}, id="uk-date"
        ),
    ],
)
def test_clean_step_rejects(values):
    with pytest.raises(SynthesisError):
        clean_step(values)


def test_clean_step_temperature_limits_are_allowed():
    assert clean_step({"step_type": "x", "temperature_c": "-273"})["temperature_c"]
    assert clean_step({"step_type": "x", "temperature_c": "2000"})["temperature_c"]


# --- Database -------------------------------------------------------------------


@pytest.fixture
def material():
    """A test material, deleted afterwards along with its steps."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO tbl_materials (material_id) VALUES (%s)", (TEST_MATERIAL,))
    conn.commit()
    try:
        yield TEST_MATERIAL
    finally:
        cur.execute(
            "DELETE FROM tbl_materials WHERE material_id = %s", (TEST_MATERIAL,)
        )
        conn.commit()
        cur.close()
        conn.close()


@needs_database
def test_add_numbers_steps_in_order(material):
    first = add_step(material, {"step_type": "mixing"})
    second = add_step(material, {"step_type": "calcination", "temperature_c": "900"})
    assert first["step_no"] == 1
    assert second["step_no"] == 2
    assert second["temperature_c"] == 900.0
    steps = list_steps(material)
    assert [s["step_type"] for s in steps] == ["mixing", "calcination"]


@needs_database
def test_add_duplicate_step_no_rejected(material):
    add_step(material, {"step_type": "mixing", "step_no": "1"})
    with pytest.raises(SynthesisError, match="Step 1 already exists"):
        add_step(material, {"step_type": "drying", "step_no": "1"})


@needs_database
def test_add_to_missing_material_rejected():
    with pytest.raises(SynthesisError, match="doesn't exist"):
        add_step("TEST-SYNTH-MISSING", {"step_type": "mixing"})


@needs_database
def test_update_changes_values(material):
    step = add_step(material, {"step_type": "mixing", "notes": "first try"})
    updated = update_step(
        step["step_id"],
        {"step_type": "milling", "duration_h": "2", "performed_on": "2026-11-12"},
    )
    assert updated["step_no"] == 1  # blank step number keeps the old one
    assert updated["step_type"] == "milling"
    assert updated["duration_h"] == 2.0
    assert updated["notes"] is None  # blank clears it
    assert updated["performed_on"] == "2026-11-12"
    assert get_step(step["step_id"]) == updated


@needs_database
def test_update_to_taken_step_no_rejected(material):
    add_step(material, {"step_type": "mixing"})
    second = add_step(material, {"step_type": "drying"})
    with pytest.raises(SynthesisError, match="Step 1 already exists"):
        update_step(second["step_id"], {"step_type": "drying", "step_no": "1"})


@needs_database
def test_update_missing_step_is_none():
    assert update_step(-1, {"step_type": "mixing"}) is None


@needs_database
def test_delete_step(material):
    step = add_step(material, {"step_type": "sieving"})
    assert delete_step(step["step_id"]) is True
    assert delete_step(step["step_id"]) is False
    assert list_steps(material) == []
