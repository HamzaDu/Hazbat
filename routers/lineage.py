"""Lineage & passport page for cells, and its JSON export.

The data is built in services/lineage.py. Template: lineage.html.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from core.auth import get_allowed_projects, require_login
from core.db import get_connection
from core.templates import templates
from services.lineage import build_lineage, to_jsonable
from services.records import CELL_TYPES, detect_record_type, record_visible

router = APIRouter()


@router.get("/card/{record_id}/lineage", response_class=HTMLResponse)
def lineage_page(request: Request, record_id: str):
    """Lineage & passport page for a cell (other records are sent to their basic card)."""
    redirect = require_login(request)
    if redirect:
        return redirect
    record_type = detect_record_type(record_id)
    if not record_type:
        return HTMLResponse("Unrecognised ID format.", status_code=404)
    if record_type not in CELL_TYPES:
        return RedirectResponse(url=f"/card/{record_id}", status_code=303)
    if not record_visible(record_id, get_allowed_projects(request)):
        return HTMLResponse("Record not found.", status_code=404)

    conn = get_connection(read_only=True)
    cur = conn.cursor()
    lineage = build_lineage(cur, record_type, record_id)
    cur.close()
    conn.close()

    if not lineage:
        return HTMLResponse("Record not found.", status_code=404)
    return templates.TemplateResponse(request, "lineage.html", {"l": lineage})


@router.get("/api/lineage/{record_id}")
def lineage_data(request: Request, record_id: str):
    """Lineage & passport data for one cell as JSON (also the "Export JSON" button)."""
    redirect = require_login(request)
    if redirect:
        return redirect
    record_type = detect_record_type(record_id)
    if record_type not in CELL_TYPES:
        return JSONResponse({"error": "Lineage is only available for cells (SLP, coin cell, MLP)"}, status_code=404)
    if not record_visible(record_id, get_allowed_projects(request)):
        return JSONResponse({"error": "Record not found"}, status_code=404)

    conn = get_connection(read_only=True)
    cur = conn.cursor()
    lineage = build_lineage(cur, record_type, record_id)
    cur.close()
    conn.close()

    if not lineage:
        return JSONResponse({"error": "Record not found"}, status_code=404)
    return JSONResponse(to_jsonable(lineage))
