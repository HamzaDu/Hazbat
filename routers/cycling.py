"""Cycling data: .mpr upload, capacity / efficiency / state-of-health summary, voltage curves.

File reading lives in services/cycling.py. Template: cycling_upload.html.
"""

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from core.auth import get_allowed_projects, require_login
from core.db import get_connection
from core.templates import templates
from services.cycling import group_full_cycles, latest_cycling_file, read_half_cycles, upload_path, valid_record_id
from services.records import record_visible

router = APIRouter()


# --- Upload ------------------------------------------------------------------

@router.get("/cycling/upload", response_class=HTMLResponse)
def cycling_upload_form(request: Request):
    """Form for uploading a BioLogic .mpr file for a record."""
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "cycling_upload.html")


@router.post("/cycling/upload", response_class=HTMLResponse)
async def cycling_upload_submit(request: Request, record_id: str = Form(...), file: UploadFile = File(...)):
    """Save the uploaded .mpr file, read its size and cycle count, and log it in tbl_cycling_data."""
    redirect = require_login(request)
    if redirect:
        return redirect

    record_id = record_id.strip().upper()
    error = None
    success = None

    if not record_id:
        error = "Record ID is required."
    elif not file.filename.endswith(".mpr"):
        error = "Only .mpr files are supported."
    elif not valid_record_id(record_id):
        error = "Record ID may only contain letters, numbers and hyphens."
    elif not record_visible(record_id, get_allowed_projects(request)):
        error = "Record not found."
    else:
        save_path = upload_path(record_id, file.filename)

        contents = await file.read()
        with open(save_path, "wb") as f:
            f.write(contents)

        try:
            from galvani import BioLogic
            mpr = BioLogic.MPRfile(str(save_path))
            num_points = len(mpr.data)
            max_capacity = float(mpr.data["Q charge/discharge/mA.h"].max())
            num_cycles = int(mpr.data["half cycle"].max()) + 1

            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO tbl_cycling_data (record_id, filename, file_path, num_points, max_capacity_mah, num_cycles) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (record_id, file.filename, str(save_path), num_points, max_capacity, num_cycles)
            )
            conn.commit()
            cur.close()
            conn.close()
            success = f"Uploaded and parsed {num_points} data points for {record_id} ({num_cycles} half-cycles)."
        except Exception as e:
            error = f"Failed to parse file: {str(e)}"

    return templates.TemplateResponse(request, "cycling_upload.html", {"error": error, "success": success})


# --- Summary and voltage curves ----------------------------------------------

@router.get("/api/cycling/{record_id}/summary")
def cycling_summary(request: Request, record_id: str):
    """Capacity per half-cycle, coulombic efficiency and state of health from the latest file."""
    redirect = require_login(request)
    if redirect:
        return redirect
    if not record_visible(record_id, get_allowed_projects(request)):
        return JSONResponse({"error": "No cycling data found for this record"}, status_code=404)
    file_path = latest_cycling_file(record_id)

    if not file_path:
        return JSONResponse({"error": "No cycling data found for this record"}, status_code=404)

    from galvani import BioLogic
    mpr = BioLogic.MPRfile(file_path)
    data = mpr.data

    cycles = sorted(set(int(x) for x in data["half cycle"]))
    capacity_per_cycle = []
    is_charge = []

    for c in cycles:
        mask = data["half cycle"] == c
        q_values = data["Q charge/discharge/mA.h"][mask]
        if len(q_values) < 2:
            capacity_per_cycle.append(0.0)
            is_charge.append(None)
            continue
        delta = float(q_values[-1]) - float(q_values[0])
        capacity_per_cycle.append(abs(delta))
        is_charge.append(delta > 0)

    # Real cycles only — drop negligible rest/OCV segments (capacity below 0.01 mAh)
    real_cycles = [(c, cap, chg) for c, cap, chg in zip(cycles, capacity_per_cycle, is_charge) if cap > 0.01]

    # Pair each charge with the discharge that follows it
    efficiency = []
    eff_cycle_numbers = []
    for i in range(len(real_cycles) - 1):
        c1, cap1, chg1 = real_cycles[i]
        c2, cap2, chg2 = real_cycles[i + 1]
        if chg1 is True and chg2 is False and cap1 > 0:
            efficiency.append(round((cap2 / cap1) * 100, 2))
            eff_cycle_numbers.append(c2)

    # State of health: latest discharge capacity as a % of the first discharge
    discharge = [cap for _, cap, chg in real_cycles if chg is False]
    soh_pct = round(discharge[-1] / discharge[0] * 100, 1) if len(discharge) >= 2 and discharge[0] > 0 else None

    return JSONResponse({
        "cycles": cycles,
        "capacity_per_cycle": capacity_per_cycle,
        "efficiency": efficiency,
        "efficiency_cycle_numbers": eff_cycle_numbers,
        "discharge_capacity_mah": discharge,
        "soh_pct": soh_pct
    })


@router.get("/api/cycling/{record_id}/curves")
def cycling_curves(request: Request, record_id: str, cycles: str = "1,2"):
    """Voltage vs capacity for chosen full cycles, e.g. ?cycles=1,2,last or ?cycles=all (max 20)."""
    redirect = require_login(request)
    if redirect:
        return redirect
    if not record_visible(record_id, get_allowed_projects(request)):
        return JSONResponse({"error": "No cycling data found for this record"}, status_code=404)
    file_path = latest_cycling_file(record_id)
    if not file_path:
        return JSONResponse({"error": "No cycling data found for this record"}, status_code=404)
    try:
        full = group_full_cycles(read_half_cycles(file_path))
    except Exception as e:
        return JSONResponse({"error": f"Could not read cycling file: {e}"}, status_code=422)

    if cycles == "all":
        wanted = full[:20]
    else:
        numbers = set()
        for part in cycles.split(","):
            part = part.strip().lower()
            if part == "last" and full:
                numbers.add(full[-1]["cycle"])
            elif part.isdigit():
                numbers.add(int(part))
        wanted = [c for c in full if c["cycle"] in numbers]

    return JSONResponse({"record_id": record_id, "n_cycles": len(full), "cycles": wanted})


@router.get("/api/cycling/{record_id}/cycle/{half_cycle}")
def cycling_half_cycle(request: Request, record_id: str, half_cycle: str):
    """One half-cycle's voltage curve (used by the graph page's voltage-capacity view)."""
    redirect = require_login(request)
    if redirect:
        return redirect
    if not record_visible(record_id, get_allowed_projects(request)):
        return JSONResponse({"error": "No cycling data found for this record"}, status_code=404)
    file_path = latest_cycling_file(record_id)
    if not file_path:
        return JSONResponse({"error": "No cycling data found for this record"}, status_code=404)
    if not half_cycle.isdigit():
        return JSONResponse({"error": "Half-cycle must be a number"}, status_code=400)
    try:
        halves = read_half_cycles(file_path)
    except Exception as e:
        return JSONResponse({"error": f"Could not read cycling file: {e}"}, status_code=422)
    match = next((h for h in halves if h["half_cycle"] == int(half_cycle)), None)
    if not match:
        return JSONResponse({"error": "That half-cycle has no charge or discharge data"}, status_code=404)
    return JSONResponse(match)
