"""Helpers for the "New record" forms (routers/records.py) and bulk upload.

Cleans optional form values, inserts rows and fills the dropdown lists.
Tables: tbl_materials, tbl_coating, tbl_projects (read), any table (insert_record).
"""

import re

import psycopg2

from core.db import get_connection

FIELD_LABELS = {
    "quantity_kg": "Quantity (kg)",
    "coat_weight_gsm": "Coat weight (g/m²)",
    "porosity": "Porosity",
    "formation_capacity": "Formation capacity",
    "np_ratio": "N/P ratio",
    "cell_capacity": "Cell capacity",
    "ac_area_ratio": "A/C area ratio",
    "gsm": "GSM",
}

# Cathodes per MLP cell. The database CHECK on tbl_mlp.cathode_count matches.
DEFAULT_CATHODES = 1
MIN_CATHODES = 1
MAX_CATHODES = 100


def clean_optional_fields(values: dict, numeric_fields=()):
    """Tidy optional form values: blank -> None, numbers -> float.
    Returns (cleaned_dict, None) or (None, error_message)."""
    cleaned = {}
    for field, value in values.items():
        value = (value or "").strip()
        if value == "":
            cleaned[field] = None
        elif field in numeric_fields:
            label = FIELD_LABELS.get(field, field)
            try:
                number = float(value)
            except ValueError:
                return None, f"{label} must be a number."
            if number < 0:
                return None, f"{label} cannot be negative."
            cleaned[field] = number
        else:
            cleaned[field] = value
    return cleaned, None


def parse_cathode_count(value):
    """Number of cathodes in an MLP from a form or spreadsheet cell: blank -> 1.
    Returns (count, None) or (None, error_message)."""
    value = (value or "").strip()
    if value == "":
        return DEFAULT_CATHODES, None
    error = (
        f"Number of cathodes must be a whole number from {MIN_CATHODES} to "
        f"{MAX_CATHODES} (got '{value}')."
    )
    if not re.fullmatch(r"[0-9]+", value):
        return None, error
    count = int(value)
    if count < MIN_CATHODES or count > MAX_CATHODES:
        return None, error
    return count, None


def insert_record(table: str, data: dict):
    """INSERT one row. Table/column names come from our own code, never from the user.
    Returns None on success or an error message."""
    columns = ", ".join(data.keys())
    placeholders = ", ".join(["%s"] * len(data))
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            list(data.values()),
        )
        conn.commit()
        return None
    except psycopg2.Error as e:
        conn.rollback()
        return str(e)
    finally:
        cur.close()
        conn.close()


def form_state(*dicts):
    """Values to re-fill the form with if saving fails, so nothing has to be retyped."""
    merged = {}
    for d in dicts:
        merged.update({k: (v or "").strip() for k, v in d.items()})
    return merged


def record_exists(table: str, id_column: str, value: str) -> bool:
    """True if a row with this ID exists. Table/column names come from our own code."""
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT 1 FROM {table} WHERE {id_column} = %s", (value,))
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()


def coating_electrode(coating_id: str):
    """'cathode' / 'anode' for a coating (from its material's CAT-/AN- prefix),
    or None if not found.
    """
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT material_id FROM tbl_coating WHERE coating_id = %s", (coating_id,)
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    if not row:
        return None
    return (
        "cathode"
        if row[0].startswith("CAT-")
        else "anode"
        if row[0].startswith("AN-")
        else "unknown"
    )


def load_form_options():
    """Lists that fill the dropdowns on the New Coating / SLP / Coin Cell /
    MLP forms.
    """
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT project_name FROM tbl_projects WHERE active ORDER BY project_name"
        )
        projects = [r[0] for r in cur.fetchall()]

        cur.execute(
            "SELECT material_id, chemistry, supplier FROM tbl_materials "
            "ORDER BY material_id"
        )
        materials = [
            {
                "id": r[0],
                "label": " · ".join(str(x) for x in r[1:] if x),
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT c.coating_id, c.material_id, m.chemistry, c.coating_date "
            "FROM tbl_coating c "
            "LEFT JOIN tbl_materials m ON m.material_id = c.material_id "
            "ORDER BY c.coating_id"
        )
        coatings = []
        for coating_id, material_id, chemistry, coating_date in cur.fetchall():
            label = " · ".join(
                str(x) for x in (chemistry or material_id, coating_date) if x
            )
            electrode = (
                "cathode"
                if material_id.startswith("CAT-")
                else "anode"
                if material_id.startswith("AN-")
                else ""
            )
            coatings.append({"id": coating_id, "label": label, "electrode": electrode})
    finally:
        cur.close()
        conn.close()

    return {
        "projects": projects,
        "materials": materials,
        "coatings": coatings,
        "cat_coatings": [c for c in coatings if c["electrode"] == "cathode"],
        "an_coatings": [c for c in coatings if c["electrode"] == "anode"],
    }
