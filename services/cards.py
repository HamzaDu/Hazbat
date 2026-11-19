"""Record cards: one lookup shared by /card, /api/card, the graph side panel
and the lineage page.

CARD_FIELDS says which columns each record type shows and with what label.
PANEL_FIELDS picks the six quick-view fields for cells in the graph panel.
"""

import io

import qrcode

from services.records import CELL_TYPES

# For each record type: (table, ID column, [(column, label shown on the card), ...])
CARD_FIELDS = {
    "material": (
        "tbl_materials",
        "material_id",
        [
            ("chemistry", "Chemistry"),
            ("supplier", "Supplier"),
            ("date_received", "Date Received"),
            ("quantity_kg", "Quantity (kg)"),
            ("location", "Location"),
            ("availability", "Availability"),
            ("notes", "Notes"),
        ],
    ),
    "coating": (
        "tbl_coating",
        "coating_id",
        [
            ("material_id", "Material ID"),
            ("project", "Project"),
            ("coating_date", "Coating Date"),
            ("made_by", "Made By"),
            ("coat_weight_gsm", "GSM"),
            ("porosity", "Porosity"),
            ("notes", "Notes"),
        ],
    ),
    "slp": (
        "tbl_slp",
        "slp_id",
        [
            ("coating_id", "Coating ID"),
            ("project", "Project"),
            ("date_made", "Date Made"),
            ("made_by", "Made By"),
            ("electrolyte", "Electrolyte"),
            ("formation_capacity", "Formation Capacity"),
            ("np_ratio", "N/P Ratio"),
            ("notes", "Notes"),
        ],
    ),
    "coincell": (
        "tbl_coincell",
        "coincell_id",
        [
            ("coating_id", "Coating ID"),
            ("project", "Project"),
            ("date_made", "Date Made"),
            ("made_by", "Made By"),
            ("electrolyte", "Electrolyte"),
            ("formation_capacity", "Formation Capacity"),
            ("gsm", "GSM"),
            ("notes", "Notes"),
            ("cell_type", "Cell Type"),
        ],
    ),
    "mlp": (
        "tbl_mlp",
        "mlp_id",
        [
            ("cat_coating_id", "Cathode Coating"),
            ("an_coating_id", "Anode Coating"),
            ("project", "Project"),
            ("date_made", "Date Made"),
            ("cell_capacity", "Cell Capacity"),
            ("electrolyte", "Electrolyte"),
            ("ac_area_ratio", "A/C Area Ratio"),
            ("cathode_count", "Cathodes"),
            ("anode_count", "Anodes"),
        ],
    ),
}

# The six quick-view fields shown in the graph side panel, per cell type.
# "Chemistry" is looked up from the material(s) behind the cell's coating(s).
PANEL_FIELDS = {
    "slp": [
        "Chemistry",
        "Formation Capacity",
        "Electrolyte",
        "N/P Ratio",
        "Project",
        "Date Made",
    ],
    "coincell": [
        "Chemistry",
        "Formation Capacity",
        "Electrolyte",
        "Cell Type",
        "Project",
        "Date Made",
    ],
    "mlp": [
        "Chemistry",
        "Cell Capacity",
        "Electrolyte",
        "A/C Area Ratio",
        "Project",
        "Date Made",
    ],
}


def fetch_card_record(cur, record_type: str, record_id: str):
    """Look up one record. Returns (record, chain): record is {label: value}
    (None if not found) and chain lists the linked records."""
    table, id_column, fields = CARD_FIELDS[record_type]
    columns = ", ".join(column for column, _ in fields)
    # Table/column names come from CARD_FIELDS above, never from the user.
    cur.execute(f"SELECT {columns} FROM {table} WHERE {id_column} = %s", (record_id,))
    row = cur.fetchone()
    if not row:
        return None, []
    record = {label: value for (_, label), value in zip(fields, row, strict=True)}

    chain = []
    if record_type == "material":
        cur.execute(
            "SELECT coating_id FROM tbl_coating WHERE material_id = %s", (record_id,)
        )
        chain += [f"Coating: {r[0]}" for r in cur.fetchall()]
    elif record_type == "coating":
        cur.execute("SELECT slp_id FROM tbl_slp WHERE coating_id = %s", (record_id,))
        chain += [f"SLP: {r[0]}" for r in cur.fetchall()]
        cur.execute(
            "SELECT coincell_id FROM tbl_coincell WHERE coating_id = %s", (record_id,)
        )
        chain += [f"CoinCell: {r[0]}" for r in cur.fetchall()]
        cur.execute(
            "SELECT mlp_id FROM tbl_mlp "
            "WHERE cat_coating_id = %s OR an_coating_id = %s",
            (record_id, record_id),
        )
        chain += [f"MLP: {r[0]}" for r in cur.fetchall()]
    elif record_type in ("slp", "coincell"):
        chain.append(f"Coating: {record['Coating ID']}")
    elif record_type == "mlp":
        chain.append(f"Cathode: {record['Cathode Coating']}")
        chain.append(f"Anode: {record['Anode Coating']}")
    return record, chain


def coating_chemistry(cur, coating_id: str):
    """Chemistry of the material a coating was made from (None if unknown)."""
    cur.execute(
        "SELECT m.chemistry FROM tbl_coating c "
        "JOIN tbl_materials m ON m.material_id = c.material_id "
        "WHERE c.coating_id = %s",
        (coating_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def panel_fields(cur, record_type: str, record: dict):
    """The six quick-view fields for a cell, as [[label, value], ...] (value
    None if blank).
    """
    if record_type == "mlp":
        cathode = coating_chemistry(cur, record["Cathode Coating"]) or "?"
        anode = coating_chemistry(cur, record["Anode Coating"]) or "?"
        chemistry = f"{cathode} ‖ {anode}"
    else:
        chemistry = coating_chemistry(cur, record["Coating ID"])
    values = {**record, "Chemistry": chemistry}
    return [
        [label, None if values.get(label) is None else str(values[label])]
        for label in PANEL_FIELDS[record_type]
    ]


def make_qr_png(url: str) -> bytes:
    """PNG bytes of a QR code that opens the given URL."""
    buf = io.BytesIO()
    qrcode.make(url).save(buf, format="PNG")
    return buf.getvalue()


def card_path(record_id: str, record_type: str) -> str:
    """Page a QR code should open: the lineage & passport page for cells, the
    basic card otherwise.
    """
    if record_type in CELL_TYPES:
        return f"/card/{record_id}/lineage"
    return f"/card/{record_id}"
