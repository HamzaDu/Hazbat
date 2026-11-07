"""Reading BioLogic .mpr cycling files with galvani (routers/cycling.py).

Files are saved in uploads/cycling_data/ and listed in tbl_cycling_data.
Each file is split into half-cycles (charge or discharge) for the voltage curves.
"""

import os
import re
from pathlib import Path

from core.db import get_connection


UPLOAD_DIR = Path("uploads/cycling_data")
VOLTAGE_COLUMNS = ("Ewe/V", "Ecell/V", "<Ewe>/V")   # BioLogic names, first one found is used
MAX_POINTS_PER_CURVE = 400                          # keeps the JSON small for long files


def valid_record_id(record_id: str) -> bool:
    """True if the ID is only letters, digits and hyphens, so it is safe to use in a file name."""
    return re.fullmatch(r"[A-Za-z0-9-]+", record_id) is not None


def upload_path(record_id: str, filename: str):
    """Where an uploaded file is saved: always directly inside UPLOAD_DIR, whatever the file is called.
    Only the last part of the name is kept, and anything but letters, digits, '.', '-' and '_' becomes '_'.
    record_id must already have passed valid_record_id()."""
    last_part = os.path.basename(filename.replace("\\", "/"))
    name = re.sub(r"[^A-Za-z0-9._-]", "_", last_part).lstrip(".")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{record_id}_{name}"
    if path.resolve().parent != UPLOAD_DIR.resolve():
        raise ValueError("File name is not allowed.")
    return path


def stored_file(file_path: str):
    """The stored path if it is directly inside UPLOAD_DIR, otherwise None.
    The database is not trusted to hold a safe path."""
    path = Path(file_path).resolve()
    if path.parent != UPLOAD_DIR.resolve():
        return None
    return str(path)


def latest_cycling_file(record_id: str):
    """Path of the most recently uploaded .mpr file for a record (None if there isn't one)."""
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    cur.execute(
        "SELECT file_path FROM tbl_cycling_data WHERE record_id = %s ORDER BY uploaded_at DESC LIMIT 1",
        (record_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return stored_file(row[0])


def read_half_cycles(file_path: str):
    """Split a BioLogic file into half-cycles with their voltage curve.
    Returns [{"half_cycle", "is_charge", "capacity_mah": [...], "voltage_v": [...]}, ...];
    capacity restarts from 0 at the start of each half-cycle. Rests (< 0.01 mAh) are dropped."""
    from galvani import BioLogic
    data = BioLogic.MPRfile(file_path).data
    names = data.dtype.names if hasattr(data, "dtype") and data.dtype.names else list(data.keys())
    v_col = next((c for c in VOLTAGE_COLUMNS if c in names), None)
    if v_col is None:
        raise ValueError("No voltage column (Ewe/V) found in this file")

    halves = []
    for c in sorted(set(int(x) for x in data["half cycle"])):
        mask = data["half cycle"] == c
        q = data["Q charge/discharge/mA.h"][mask]
        v = data[v_col][mask]
        if len(q) < 2:
            continue
        delta = float(q[-1]) - float(q[0])
        if abs(delta) <= 0.01:
            continue  # rest / OCV segment
        # Keep at most MAX_POINTS_PER_CURVE points, always including the last one (end capacity)
        step = max(1, -(-len(q) // MAX_POINTS_PER_CURVE))  # ceiling division
        keep = list(range(0, len(q), step))
        if keep[-1] != len(q) - 1:
            keep.append(len(q) - 1)
        q0 = float(q[0])
        halves.append({
            "half_cycle": c,
            "is_charge": delta > 0,
            "capacity_mah": [round(abs(float(q[i]) - q0), 5) for i in keep],
            "voltage_v": [round(float(v[i]), 4) for i in keep],
        })
    return halves


def group_full_cycles(halves):
    """Pair each charge with the discharge after it: [{"cycle": 1, "charge": {...}, "discharge": {...}}, ...].
    A discharge with no charge before it (e.g. a cathode half cell) starts its own cycle."""
    cycles = []
    for h in halves:
        part = {"capacity_mah": h["capacity_mah"], "voltage_v": h["voltage_v"], "half_cycle": h["half_cycle"]}
        if h["is_charge"]:
            cycles.append({"charge": part})
        elif cycles and "discharge" not in cycles[-1]:
            cycles[-1]["discharge"] = part
        else:
            cycles.append({"discharge": part})
    for number, cycle in enumerate(cycles, start=1):
        cycle["cycle"] = number
    return cycles
