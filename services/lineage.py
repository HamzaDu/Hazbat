"""Lineage & passport page data (routers/lineage.py, templates/lineage.html).

build_lineage() collects one cell's materials, coatings, process steps,
usage (cycling data) and end-of-life details, plus a passport completeness score.
Values not recorded yet stay None and show as "—".
"""

from services.cards import fetch_card_record

# Process energy is not recorded yet, so it stays None (shown as "—") until
# process-step data is added to the database. Cost and carbon are deliberately
# not part of the passport: they need a proper study, not a rough estimate.
EMPTY_PROCESS_METRICS = {"energy_kwh": None, "data_quality": None}


def to_jsonable(value):
    """Make dates and Decimals from Postgres safe for JSON."""
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is not None and type(value).__name__ == "Decimal":
        return float(value)
    return value


def electrode_role(material_id: str) -> str:
    """'Cathode' / 'Anode' from a CAT- / AN- material ID ('Electrode' if neither)."""
    rid = (material_id or "").upper()
    if rid.startswith("CAT"):
        return "Cathode"
    if rid.startswith("AN"):
        return "Anode"
    return "Electrode"


def coating_with_material(cur, coating_id: str):
    """One branch of the lineage: the coating and the material it was made from."""
    cur.execute(
        "SELECT material_id, project, coating_date, made_by, "
        "coat_weight_gsm, porosity, notes "
        "FROM tbl_coating WHERE coating_id = %s",
        (coating_id,),
    )
    row = cur.fetchone()
    keys = [
        "material_id",
        "project",
        "coating_date",
        "made_by",
        "coat_weight_gsm",
        "porosity",
        "notes",
    ]
    coating = {
        "id": coating_id,
        **(dict(zip(keys, row, strict=True)) if row else {k: None for k in keys}),
    }

    material = None
    if coating["material_id"]:
        cur.execute(
            "SELECT chemistry, supplier, date_received, quantity_kg, "
            "location, availability "
            "FROM tbl_materials WHERE material_id = %s",
            (coating["material_id"],),
        )
        row = cur.fetchone()
        keys = [
            "chemistry",
            "supplier",
            "date_received",
            "quantity_kg",
            "location",
            "availability",
        ]
        material = {
            "id": coating["material_id"],
            **(dict(zip(keys, row, strict=True)) if row else {k: None for k in keys}),
            "recycled_content": None,
        }

    return {
        "role": electrode_role(coating["material_id"] or coating_id),
        "material": material,
        "process": {
            "name": "Electrode manufacture",
            "steps": "Mix → Coat → Dry → Calender",
            "date": coating["coating_date"],
            "operator": coating["made_by"],
            "location": None,
            **EMPTY_PROCESS_METRICS,
        },
        "coating": coating,
    }


def build_lineage(cur, record_type: str, record_id: str):
    """Everything the lineage & passport page shows for one cell (None if not found)."""
    record, chain = fetch_card_record(cur, record_type, record_id)
    if not record:
        return None

    if record_type == "mlp":
        coating_ids = [record["Cathode Coating"], record["Anode Coating"]]
    else:
        coating_ids = [record["Coating ID"]]
    branches = [coating_with_material(cur, cid) for cid in coating_ids]

    cur.execute(
        "SELECT filename, num_cycles, uploaded_at FROM tbl_cycling_data "
        "WHERE record_id = %s ORDER BY uploaded_at DESC LIMIT 1",
        (record_id,),
    )
    row = cur.fetchone()
    cycling = (
        {"filename": row[0], "half_cycles": row[1], "uploaded_at": row[2]}
        if row
        else None
    )

    chemistry = " ‖ ".join(
        (b["material"] or {}).get("chemistry") or "?" for b in branches
    )
    suppliers = [(b["material"] or {}).get("supplier") for b in branches]
    capacity = record.get("Cell Capacity") or record.get("Formation Capacity")

    lineage = {
        "record_id": record_id,
        "record_type": record_type,
        "chemistry": chemistry,
        "record": record,
        "chain": chain,
        "branches": branches,
        "assembly": {
            "name": "Cell assembly",
            "date": record.get("Date Made"),
            "operator": record.get("Made By"),
            "location": None,
            "inputs": {"electrolyte": record.get("Electrolyte")},
            **EMPTY_PROCESS_METRICS,
        },
        "formation": {
            "name": "Formation",
            "formation_capacity": record.get("Formation Capacity"),
            **EMPTY_PROCESS_METRICS,
        },
        "usage": {"type": "Testing" if cycling else None, "cycling": cycling},
        "end_of_life": {"route": None, "recycler": None, "second_life_eligible": None},
        "totals": {"energy_kwh": None},
        "qr_url": f"/qr/{record_id}.png",
    }

    # How much of the passport is filled in (a rough guide, not a compliance check)
    checks = {
        "Chemistry": "?" not in chemistry,
        "Supplier": all(suppliers),
        "Electrolyte": record.get("Electrolyte") is not None,
        "Capacity": capacity is not None,
        "Date made": record.get("Date Made") is not None,
        "Project": record.get("Project") is not None,
        "Cycling data": cycling is not None,
        "Process energy": False,
        "Recycled content": False,
        "End-of-life route": False,
    }
    lineage["completeness"] = {
        "filled": sum(checks.values()),
        "total": len(checks),
        "missing": [name for name, ok in checks.items() if not ok],
    }
    return lineage
