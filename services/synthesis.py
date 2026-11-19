"""Synthesis steps for a material (tbl_material_synthesis_step).

Checks the values a user sends with a clear message for each mistake, then reads,
adds, changes and deletes steps. The table's own rules (step_no > 0, unique per
material, temperature and duration ranges) are the backstop.
"""

import math
from datetime import date

from psycopg2 import errors

from core.db import get_connection
from services.forms import record_exists

# Suggestions for the form; any other text is allowed.
STEP_TYPES = (
    "mixing",
    "co-precipitation",
    "drying",
    "calcination",
    "milling",
    "sieving",
)

MIN_TEMPERATURE_C = -273
MAX_TEMPERATURE_C = 2000

TEXT_FIELDS = ("step_type", "atmosphere", "equipment", "notes", "performed_by")

FIELD_LABELS = {
    "step_no": "Step number",
    "step_type": "Step type",
    "temperature_c": "Temperature (°C)",
    "duration_h": "Duration (h)",
    "performed_on": "Date performed",
}

STEP_COLUMNS = (
    "step_id, material_id, step_no, step_type, temperature_c, duration_h, "
    "atmosphere, equipment, notes, performed_by, performed_on"
)


class SynthesisError(ValueError):
    """A step was rejected; the message is shown to the user."""


# --- Checking -----------------------------------------------------------------


def raw_value(values: dict, field: str):
    """The value as stripped text, or None if missing or blank."""
    value = values.get(field)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def parse_number(field: str, text):
    """A finite float from text (None stays None). Raises SynthesisError."""
    if text is None:
        return None
    label = FIELD_LABELS[field]
    try:
        number = float(text)
    except ValueError:
        raise SynthesisError(f"{label} must be a number.") from None
    if not math.isfinite(number):
        raise SynthesisError(f"{label} must be a number.")
    return number


def clean_step(values: dict) -> dict:
    """Tidy and check one step's values (strings from a form or JSON).
    Only the step's own fields are kept, so step_id or material_id in the
    input are ignored. Raises SynthesisError.
    """
    cleaned = {}
    for field in TEXT_FIELDS:
        cleaned[field] = raw_value(values, field)
    if cleaned["step_type"] is None:
        raise SynthesisError("Step type is required.")

    step_no = raw_value(values, "step_no")
    if step_no is not None:
        try:
            step_no = int(step_no)
        except ValueError:
            raise SynthesisError("Step number must be a whole number.") from None
        if step_no < 1:
            raise SynthesisError("Step number must be 1 or more.")
    cleaned["step_no"] = step_no

    temperature = parse_number("temperature_c", raw_value(values, "temperature_c"))
    if temperature is not None and not (
        MIN_TEMPERATURE_C <= temperature <= MAX_TEMPERATURE_C
    ):
        raise SynthesisError(
            f"Temperature (°C) must be between {MIN_TEMPERATURE_C} "
            f"and {MAX_TEMPERATURE_C}."
        )
    cleaned["temperature_c"] = temperature

    duration = parse_number("duration_h", raw_value(values, "duration_h"))
    if duration is not None and duration <= 0:
        raise SynthesisError("Duration (h) must be more than 0.")
    cleaned["duration_h"] = duration

    performed_on = raw_value(values, "performed_on")
    if performed_on is not None:
        try:
            performed_on = date.fromisoformat(performed_on)
        except ValueError:
            raise SynthesisError(
                "Date performed must be a date like 2026-11-12."
            ) from None
    cleaned["performed_on"] = performed_on
    return cleaned


# --- Reading --------------------------------------------------------------------


def to_float(value):
    """NUMERIC comes back as Decimal; JSON needs a float."""
    return None if value is None else float(value)


def step_dict(row) -> dict:
    """One tbl_material_synthesis_step row as a dict (pages and JSON API)."""
    (
        step_id,
        material_id,
        step_no,
        step_type,
        temperature_c,
        duration_h,
        atmosphere,
        equipment,
        notes,
        performed_by,
        performed_on,
    ) = row
    return {
        "step_id": step_id,
        "material_id": material_id,
        "step_no": step_no,
        "step_type": step_type,
        "temperature_c": to_float(temperature_c),
        "duration_h": to_float(duration_h),
        "atmosphere": atmosphere,
        "equipment": equipment,
        "notes": notes,
        "performed_by": performed_by,
        "performed_on": performed_on.isoformat() if performed_on else None,
    }


def list_steps(material_id: str) -> list:
    """Every step for a material, in order."""
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT {STEP_COLUMNS} FROM tbl_material_synthesis_step "
            "WHERE material_id = %s ORDER BY step_no",
            (material_id,),
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()
    return [step_dict(r) for r in rows]


def get_step(step_id: int):
    """One step by ID (None if not found)."""
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT {STEP_COLUMNS} FROM tbl_material_synthesis_step "
            "WHERE step_id = %s",
            (step_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    return step_dict(row) if row else None


# --- Writing --------------------------------------------------------------------


def duplicate_message(material_id: str, step_no) -> str:
    if step_no is None:
        return f"That step number already exists for {material_id}."
    return f"Step {step_no} already exists for {material_id}."


def add_step(material_id: str, values: dict) -> dict:
    """Check and add a step. Without a step number it goes after the last one.
    Returns the new step (see step_dict). Raises SynthesisError.
    """
    step = clean_step(values)
    if not record_exists("tbl_materials", "material_id", material_id):
        raise SynthesisError(f"Material {material_id} doesn't exist.")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO tbl_material_synthesis_step "
            "(material_id, step_no, step_type, temperature_c, duration_h, "
            "atmosphere, equipment, notes, performed_by, performed_on) "
            "VALUES (%s, COALESCE(%s, (SELECT COALESCE(MAX(step_no), 0) + 1 "
            "FROM tbl_material_synthesis_step WHERE material_id = %s)), "
            "%s, %s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {STEP_COLUMNS}",
            (
                material_id,
                step["step_no"],
                material_id,
                step["step_type"],
                step["temperature_c"],
                step["duration_h"],
                step["atmosphere"],
                step["equipment"],
                step["notes"],
                step["performed_by"],
                step["performed_on"],
            ),
        )
        row = cur.fetchone()
        conn.commit()
    except errors.UniqueViolation:
        conn.rollback()
        raise SynthesisError(duplicate_message(material_id, step["step_no"])) from None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return step_dict(row)


def update_step(step_id: int, values: dict):
    """Check and replace a step's values. A blank field clears it; a blank step
    number keeps the current one. Returns the step, or None if it doesn't exist.
    Raises SynthesisError.
    """
    step = clean_step(values)
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE tbl_material_synthesis_step SET "
            "step_no = COALESCE(%s, step_no), step_type = %s, temperature_c = %s, "
            "duration_h = %s, atmosphere = %s, equipment = %s, notes = %s, "
            "performed_by = %s, performed_on = %s "
            f"WHERE step_id = %s RETURNING {STEP_COLUMNS}",
            (
                step["step_no"],
                step["step_type"],
                step["temperature_c"],
                step["duration_h"],
                step["atmosphere"],
                step["equipment"],
                step["notes"],
                step["performed_by"],
                step["performed_on"],
                step_id,
            ),
        )
        row = cur.fetchone()
        conn.commit()
    except errors.UniqueViolation:
        conn.rollback()
        material = get_step(step_id)
        material_id = material["material_id"] if material else "this material"
        raise SynthesisError(duplicate_message(material_id, step["step_no"])) from None
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return step_dict(row) if row else None


def delete_step(step_id: int) -> bool:
    """Remove a step. Returns False if it didn't exist."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM tbl_material_synthesis_step WHERE step_id = %s", (step_id,)
        )
        deleted = cur.rowcount > 0
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return deleted
