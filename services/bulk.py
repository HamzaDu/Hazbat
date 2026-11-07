"""Bulk upload of CSV / Excel files (routers/bulk_upload.py).

Each row is checked, then inserted with insert_record(). Rows that fail are
reported with their spreadsheet row number instead of stopping the upload.
BULK_SPECS lists the required and optional columns for each table.
"""

import io
import re
from datetime import datetime

import pandas as pd

from services.forms import clean_optional_fields, coating_electrode, insert_record, record_exists
from services.records import project_visible


# Cells that mean "no data". Stored as NULL in the database and shown as "—" on every page.
BLANK_MARKERS = {"", "nan", "nat", "none", "null", "n/a", "na", "-", "—", "–"}
DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y")

# Required + optional columns for each table's bulk upload. "aliases" lets older
# spreadsheets keep working (e.g. a "GSM" column on the coatings sheet).
BULK_SPECS = {
    "tbl_materials": {"id": "material_id", "required": ["material_id", "chemistry", "supplier"],
                      "numeric": ["quantity_kg"], "dates": ["date_received"],
                      "text": ["location", "availability", "notes"], "aliases": {}},
    "tbl_coating":   {"id": "coating_id", "required": ["coating_id", "material_id", "project", "made_by"],
                      "numeric": ["coat_weight_gsm", "porosity"], "dates": ["coating_date"],
                      "text": ["notes"], "aliases": {"gsm": "coat_weight_gsm", "coat_weight": "coat_weight_gsm", "coat_weight_g_m": "coat_weight_gsm", "gsm_g_m": "coat_weight_gsm"}},
    "tbl_slp":       {"id": "slp_id", "required": ["slp_id", "coating_id", "project", "made_by"],
                      "numeric": ["formation_capacity", "np_ratio"], "dates": ["date_made"],
                      "text": ["electrolyte", "notes"], "aliases": {"n_p_ratio": "np_ratio", "formation_capacity_mah": "formation_capacity"}},
    "tbl_coincell":  {"id": "coincell_id", "required": ["coincell_id", "coating_id", "project", "made_by"],
                      "numeric": ["formation_capacity", "gsm"], "dates": ["date_made"],
                      "text": ["electrolyte", "cell_type", "notes"], "aliases": {"gsm_g_m": "gsm", "formation_capacity_mah": "formation_capacity"}},
    "tbl_mlp":       {"id": "mlp_id", "required": ["mlp_id", "cat_coating_id", "an_coating_id", "project"],
                      "numeric": ["cell_capacity", "ac_area_ratio"], "dates": ["date_made"],
                      "text": ["electrolyte"], "aliases": {"a_c_area_ratio": "ac_area_ratio"}},
}


def normalise_header(name) -> str:
    """'Material ID ' / 'material-id' / 'Quantity (kg)' -> 'material_id' / 'material_id' / 'quantity_kg'."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def clean_cell(value):
    """Tidy one spreadsheet cell; N/A, -, blank etc. become None."""
    if value is None:
        return None
    value = str(value).strip()
    return None if value.lower() in BLANK_MARKERS else value


def parse_date(value: str) -> str:
    """Accepts 2026-09-24 or 24/09/2026 (UK day-first) etc.; returns ISO YYYY-MM-DD."""
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"'{value}' is not a valid date (use YYYY-MM-DD or DD/MM/YYYY).")


def read_upload(contents: bytes, filename: str):
    """Read a CSV/Excel upload as text so nothing is silently converted. Returns a list of row dicts."""
    buffer = io.BytesIO(contents)
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(buffer, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(buffer, dtype=str)
    return df.to_dict("records")


def process_bulk_upload(rows, table: str, allowed, check=None):
    """Validate and insert each row. A row for a project the user may not use fails (allowed is None for admins).
    check(values) may return an error message for a row.
    Returns {"success": [...ids], "failed": [{"row", "reason"}], "ignored": [...unknown columns]}."""
    spec = BULK_SPECS[table]
    known = spec["required"] + spec["numeric"] + spec["dates"] + spec["text"]
    success, failed, ignored = [], [], set()

    for i, raw in enumerate(rows):
        row_num = i + 2  # +2 = header row + 1-based numbering, matching the spreadsheet
        values = {}
        for header, cell in raw.items():
            key = normalise_header(header)
            key = spec["aliases"].get(key, key)
            if key in known:
                values[key] = clean_cell(cell)
            elif key and not key.startswith("unnamed"):
                ignored.add(str(header).strip())

        if all(values.get(k) is None for k in known):
            continue  # completely empty row, e.g. trailing blank lines in Excel

        missing = [k for k in spec["required"] if not values.get(k)]
        if missing:
            failed.append({"row": row_num, "reason": f"Missing required field(s): {', '.join(missing)}."})
            continue

        if "project" in spec["required"] and not project_visible(values["project"], allowed):
            failed.append({"row": row_num, "reason": f"You don't have access to project '{values['project']}'."})
            continue

        record_id = values[spec["id"]]
        if record_id != record_id.upper():
            failed.append({"row": row_num, "reason": f"'{record_id}' is not uppercase."})
            continue

        error = check(values) if check else None
        if error:
            failed.append({"row": row_num, "reason": error})
            continue

        try:
            for field in spec["dates"]:
                if values.get(field):
                    values[field] = parse_date(values[field])
        except ValueError as e:
            failed.append({"row": row_num, "reason": str(e)})
            continue

        optional = {k: values.get(k) for k in spec["numeric"] + spec["dates"] + spec["text"]}
        extras, error = clean_optional_fields(optional, numeric_fields=set(spec["numeric"]))
        if error:
            failed.append({"row": row_num, "reason": error})
            continue

        error = insert_record(table, {**{k: values[k] for k in spec["required"]}, **extras})
        if error:
            failed.append({"row": row_num, "reason": error})
        else:
            success.append(record_id)

    return {"success": success, "failed": failed, "ignored": sorted(ignored)}


def check_material_row(v):
    """Bulk upload check: material IDs must start with CAT- or AN-."""
    if not (v["material_id"].startswith("CAT-") or v["material_id"].startswith("AN-")):
        return f"'{v['material_id']}' must start with CAT- or AN-."


def check_coating_row(v):
    """Bulk upload check: the coating's material must exist."""
    if not record_exists("tbl_materials", "material_id", v["material_id"]):
        return f"Material {v['material_id']} doesn't exist."


def check_cell_row(v):
    """Bulk upload check: the cell's coating must exist."""
    if not record_exists("tbl_coating", "coating_id", v["coating_id"]):
        return f"Coating {v['coating_id']} doesn't exist."


def check_mlp_row(v):
    """Bulk upload check: an MLP needs an existing cathode and an existing anode coating."""
    if coating_electrode(v["cat_coating_id"]) != "cathode":
        return f"{v['cat_coating_id']} isn't an existing cathode (CAT-) coating."
    if coating_electrode(v["an_coating_id"]) != "anode":
        return f"{v['an_coating_id']} isn't an existing anode (AN-) coating."
