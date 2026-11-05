"""Charts page and the small JSON endpoints that feed it (templates/chart.html)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core.auth import get_allowed_projects, require_login
from core.db import get_connection
from core.templates import templates

router = APIRouter()


@router.get("/api/chart/formation-capacity")
def chart_formation_capacity(request: Request):
    """Formation capacity of each SLP cell (bar chart data)."""
    redirect = require_login(request)
    if redirect:
        return redirect
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    allowed = get_allowed_projects(request)  # None = admin, sees everything
    extra, params = ("", ()) if allowed is None else (" AND project = ANY(%s)", (list(allowed),))
    cur.execute("SELECT slp_id, formation_capacity FROM tbl_slp WHERE formation_capacity IS NOT NULL" + extra + " ORDER BY slp_id", params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    labels = [r[0] for r in rows]
    values = [float(r[1]) for r in rows]
    return JSONResponse({"labels": labels, "values": values})

@router.get("/chart", response_class=HTMLResponse)
def chart_page(request: Request):
    """Charts page."""
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "chart.html")


@router.get("/api/chart/my-projects")
def chart_my_projects(request: Request):
    """Number of coatings and cells in each project the user can see."""
    redirect = require_login(request)
    if redirect:
        return redirect
    allowed = get_allowed_projects(request)
    conn = get_connection(read_only=True)
    cur = conn.cursor()

    if allowed is None:
        cur.execute("SELECT project_name FROM tbl_projects WHERE active = true")
        allowed = [row[0] for row in cur.fetchall()]

    results = []
    for project in allowed:
        cur.execute("SELECT COUNT(*) FROM tbl_coating WHERE project = %s", (project,))
        coatings = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tbl_slp WHERE project = %s", (project,))
        slp = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tbl_coincell WHERE project = %s", (project,))
        coincell = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tbl_mlp WHERE project = %s", (project,))
        mlp = cur.fetchone()[0]
        results.append({
            "project": project,
            "coatings": coatings,
            "slp": slp,
            "coincell": coincell,
            "mlp": mlp,
            "total": coatings + slp + coincell + mlp
        })

    cur.close()
    conn.close()
    return JSONResponse({"projects": results})


@router.get("/api/chart/gsm-by-coating")
def chart_gsm(request: Request):
    """Coat weight (g/m²) of each coating."""
    redirect = require_login(request)
    if redirect:
        return redirect
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    allowed = get_allowed_projects(request)  # None = admin, sees everything
    extra, params = ("", ()) if allowed is None else (" AND project = ANY(%s)", (list(allowed),))
    cur.execute("SELECT coating_id, coat_weight_gsm FROM tbl_coating WHERE coat_weight_gsm IS NOT NULL" + extra + " ORDER BY coating_id", params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return JSONResponse({"labels": [r[0] for r in rows], "values": [float(r[1]) for r in rows]})


@router.get("/api/chart/records-per-table")
def chart_records_per_table(request: Request):
    """How many records each table holds."""
    redirect = require_login(request)
    if redirect:
        return redirect
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    allowed = get_allowed_projects(request)  # None = admin, sees everything
    counts = {}
    for label, table in [("Materials", "tbl_materials"), ("Coatings", "tbl_coating"),
                          ("SLP", "tbl_slp"), ("Coin Cells", "tbl_coincell"), ("MLP", "tbl_mlp")]:
        # Materials have no project column
        where, params = ("", ()) if allowed is None or table == "tbl_materials" else (" WHERE project = ANY(%s)", (list(allowed),))
        cur.execute(f"SELECT COUNT(*) FROM {table}" + where, params)
        counts[label] = cur.fetchone()[0]
    cur.close()
    conn.close()
    return JSONResponse({"labels": list(counts.keys()), "values": list(counts.values())})


@router.get("/api/chart/coatings-over-time")
def chart_coatings_over_time(request: Request):
    """Number of coatings made on each date."""
    redirect = require_login(request)
    if redirect:
        return redirect
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    allowed = get_allowed_projects(request)  # None = admin, sees everything
    cur.execute("""
        SELECT coating_date, COUNT(*) 
        FROM tbl_coating 
        WHERE coating_date IS NOT NULL AND (%s OR project = ANY(%s)) 
        GROUP BY coating_date 
        ORDER BY coating_date
    """, (allowed is None, list(allowed or [])))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return JSONResponse({"labels": [str(r[0]) for r in rows], "values": [r[1] for r in rows]})
