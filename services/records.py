"""Record types and how to tell them apart from an ID.

IDs follow the naming scheme CAT-/AN- (material) -> -C001 (coating) ->
-SLP-001 / -CC01 / MLP-0001 (cells).
"""

from core.db import get_connection


def detect_record_type(record_id: str) -> str:
    """Record type from an ID: 'material', 'coating', 'slp', 'coincell', 'mlp' or None."""
    rid = record_id.upper()
    if "-SLP-" in rid:
        return "slp"
    if "MLP-" in rid:
        return "mlp"
    if "-CC" in rid:
        return "coincell"
    if "-C0" in rid or "-C1" in rid:
        return "coating"
    if rid.startswith("CAT") or rid.startswith("AN"):
        return "material"
    return None


CELL_TYPES = ("slp", "coincell", "mlp")

# Record types that belong to a project: (table, ID column). Materials do not.
PROJECT_TABLES = {
    "coating": ("tbl_coating", "coating_id"), "slp": ("tbl_slp", "slp_id"),
    "coincell": ("tbl_coincell", "coincell_id"), "mlp": ("tbl_mlp", "mlp_id"),
}


def project_visible(project: str, allowed) -> bool:
    """True if a user may use this project. allowed is the list from get_allowed_projects (None = everything)."""
    return allowed is None or project in allowed


def record_visible(record_id: str, allowed) -> bool:
    """True if a user may see this record. Materials have no project, so anyone may see them.
    An ID that is not a known type is hidden. A record that does not exist counts as visible,
    so the caller's own 'not found' applies."""
    if allowed is None:
        return True
    record_type = detect_record_type(record_id)
    if record_type == "material":
        return True
    if record_type not in PROJECT_TABLES:
        return False
    table, id_column = PROJECT_TABLES[record_type]
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    try:
        # Table/column names come from PROJECT_TABLES above, never from the user.
        cur.execute(f"SELECT project FROM {table} WHERE {id_column} = %s", (record_id,))
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    return row is None or row[0] in allowed
