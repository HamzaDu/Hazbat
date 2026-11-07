"""Traceability graph (templates/graph.html, drawn with vis-network).

/api/graph       every record as nodes and links
/api/graph/{id}  one record and its direct neighbours
/api/filters     values for the filter sidebar
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core.auth import get_allowed_projects, require_login
from core.db import get_connection
from core.templates import templates
from services.records import detect_record_type, record_visible

router = APIRouter()


# --- Whole graph -------------------------------------------------------------

@router.get("/api/graph")
def traceability_graph(request: Request):
    """Every record as graph nodes, linked material -> coating -> cell, plus dashed links to projects."""
    redirect = require_login(request)
    if redirect:
        return redirect
    conn = get_connection(read_only=True)
    cur = conn.cursor()

    allowed = get_allowed_projects(request)  # None = admin, sees everything
    where, params = ("", ()) if allowed is None else (" WHERE project = ANY(%s)", (list(allowed),))

    nodes = []
    edges = []
    seen_projects = set()

    def add_project_node(project_name):
        """Add a project node the first time that project is seen."""
        if project_name and project_name not in seen_projects:
            nodes.append({"id": f"PROJECT-{project_name}", "label": project_name, "group": "project"})
            seen_projects.add(project_name)

    cur.execute("SELECT material_id, chemistry FROM tbl_materials")
    for mat_id, chem in cur.fetchall():
        nodes.append({"id": mat_id, "label": mat_id, "group": "material", "title": chem or ""})

    cur.execute("SELECT coating_id, material_id, project FROM tbl_coating" + where, params)
    for coat_id, mat_id, project in cur.fetchall():
        nodes.append({"id": coat_id, "label": coat_id, "group": "coating"})
        edges.append({"from": mat_id, "to": coat_id})
        add_project_node(project)
        if project:
            edges.append({"from": coat_id, "to": f"PROJECT-{project}", "dashes": True})

    cur.execute("SELECT slp_id, coating_id, project FROM tbl_slp" + where, params)
    for slp_id, coat_id, project in cur.fetchall():
        nodes.append({"id": slp_id, "label": slp_id, "group": "slp"})
        edges.append({"from": coat_id, "to": slp_id})
        add_project_node(project)
        if project:
            edges.append({"from": slp_id, "to": f"PROJECT-{project}", "dashes": True})

    cur.execute("SELECT coincell_id, coating_id, project FROM tbl_coincell" + where, params)
    for cc_id, coat_id, project in cur.fetchall():
        nodes.append({"id": cc_id, "label": cc_id, "group": "coincell"})
        edges.append({"from": coat_id, "to": cc_id})
        add_project_node(project)
        if project:
            edges.append({"from": cc_id, "to": f"PROJECT-{project}", "dashes": True})

    cur.execute("SELECT mlp_id, cat_coating_id, an_coating_id, project FROM tbl_mlp" + where, params)
    for mlp_id, cat_id, an_id, project in cur.fetchall():
        nodes.append({"id": mlp_id, "label": mlp_id, "group": "mlp"})
        edges.append({"from": cat_id, "to": mlp_id})
        edges.append({"from": an_id, "to": mlp_id})
        add_project_node(project)
        if project:
            edges.append({"from": mlp_id, "to": f"PROJECT-{project}", "dashes": True})

    cur.close()
    conn.close()
    # A link to a record the user cannot see would point at a missing node
    node_ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["from"] in node_ids and e["to"] in node_ids]
    return JSONResponse({"nodes": nodes, "edges": edges})

@router.get("/graph", response_class=HTMLResponse)
def graph_page(request: Request):
    """Traceability graph page."""
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "graph.html")


# --- One record and its neighbours -------------------------------------------

@router.get("/api/graph/{record_id}")
def record_graph(request: Request, record_id: str):
    """One record with the records directly above and below it in the chain."""
    redirect = require_login(request)
    if redirect:
        return redirect
    record_type = detect_record_type(record_id)
    if not record_type:
        return JSONResponse({"error": "Unrecognised ID format"}, status_code=404)
    allowed = get_allowed_projects(request)  # None = admin, sees everything
    if not record_visible(record_id, allowed):
        return JSONResponse({"error": "Record not found"}, status_code=404)

    conn = get_connection(read_only=True)
    cur = conn.cursor()
    nodes = []
    edges = []
    seen = set()

    def add_node(node_id, group):
        """Add a node unless it is already in the graph or the user may not see it."""
        if node_id not in seen and record_visible(node_id, allowed):
            nodes.append({"id": node_id, "label": node_id, "group": group})
            seen.add(node_id)

    add_node(record_id, record_type)

    if record_type == "material":
        cur.execute("SELECT coating_id FROM tbl_coating WHERE material_id = %s", (record_id,))
        for (coating_id,) in cur.fetchall():
            add_node(coating_id, "coating")
            edges.append({"from": record_id, "to": coating_id})

    elif record_type == "coating":
        cur.execute("SELECT material_id FROM tbl_coating WHERE coating_id = %s", (record_id,))
        row = cur.fetchone()
        if row:
            add_node(row[0], "material")
            edges.append({"from": row[0], "to": record_id})

        cur.execute("SELECT slp_id FROM tbl_slp WHERE coating_id = %s", (record_id,))
        for (slp_id,) in cur.fetchall():
            add_node(slp_id, "slp")
            edges.append({"from": record_id, "to": slp_id})

        cur.execute("SELECT coincell_id FROM tbl_coincell WHERE coating_id = %s", (record_id,))
        for (cc_id,) in cur.fetchall():
            add_node(cc_id, "coincell")
            edges.append({"from": record_id, "to": cc_id})

        cur.execute("SELECT mlp_id FROM tbl_mlp WHERE cat_coating_id = %s OR an_coating_id = %s", (record_id, record_id))
        for (mlp_id,) in cur.fetchall():
            add_node(mlp_id, "mlp")
            edges.append({"from": record_id, "to": mlp_id})

    elif record_type in ("slp", "coincell"):
        table = "tbl_slp" if record_type == "slp" else "tbl_coincell"
        id_col = "slp_id" if record_type == "slp" else "coincell_id"
        cur.execute(f"SELECT coating_id FROM {table} WHERE {id_col} = %s", (record_id,))
        row = cur.fetchone()
        if row:
            coating_id = row[0]
            add_node(coating_id, "coating")
            edges.append({"from": coating_id, "to": record_id})

            cur.execute("SELECT material_id FROM tbl_coating WHERE coating_id = %s", (coating_id,))
            mat_row = cur.fetchone()
            if mat_row:
                add_node(mat_row[0], "material")
                edges.append({"from": mat_row[0], "to": coating_id})

    elif record_type == "mlp":
        cur.execute("SELECT cat_coating_id, an_coating_id FROM tbl_mlp WHERE mlp_id = %s", (record_id,))
        row = cur.fetchone()
        if row:
            for coating_id in row:
                add_node(coating_id, "coating")
                edges.append({"from": coating_id, "to": record_id})
                cur.execute("SELECT material_id FROM tbl_coating WHERE coating_id = %s", (coating_id,))
                mat_row = cur.fetchone()
                if mat_row:
                    add_node(mat_row[0], "material")
                    edges.append({"from": mat_row[0], "to": coating_id})

    cur.close()
    conn.close()
    node_ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["from"] in node_ids and e["to"] in node_ids]
    return JSONResponse({"nodes": nodes, "edges": edges})


# --- Filter options ----------------------------------------------------------

@router.get("/api/filters")
def graph_filters(request: Request):
    """
    Filter options for the traceability graph. Shape matches buildFilterUI()
    in templates/graph.html: {material:{...}, coating:{...}, cell:{...}}.
    """
    redirect = require_login(request)
    if redirect:
        return redirect
    conn = get_connection(read_only=True)
    cur = conn.cursor()

    def distinct(sql):
        """Unique non-blank values from a one-column query."""
        cur.execute(sql)
        return [r[0] for r in cur.fetchall() if r[0] not in (None, "")]

    def value_range(sql):
        """{'min', 'max'} from a MIN/MAX query, or None if there is no data."""
        cur.execute(sql)
        lo, hi = cur.fetchone()
        if lo is None or hi is None:
            return None
        return {"min": float(lo), "max": float(hi)}

    cells_made_by = distinct("""
        SELECT made_by FROM (
            SELECT made_by FROM tbl_slp
            UNION SELECT made_by FROM tbl_coincell
        ) t ORDER BY 1""")
    cells_electrolyte = distinct("""
        SELECT electrolyte FROM (
            SELECT electrolyte FROM tbl_slp
            UNION SELECT electrolyte FROM tbl_coincell
            UNION SELECT electrolyte FROM tbl_mlp
        ) t ORDER BY 1""")
    cell_capacity = value_range("""
        SELECT MIN(c), MAX(c) FROM (
            SELECT formation_capacity AS c FROM tbl_slp
            UNION ALL SELECT formation_capacity FROM tbl_coincell
            UNION ALL SELECT cell_capacity FROM tbl_mlp
        ) t""")

    result = {
        "material": {
            "chemistry":    distinct("SELECT DISTINCT chemistry FROM tbl_materials ORDER BY 1"),
            "supplier":     distinct("SELECT DISTINCT supplier FROM tbl_materials ORDER BY 1"),
            "location":     distinct("SELECT DISTINCT location FROM tbl_materials ORDER BY 1"),
            "availability": distinct("SELECT DISTINCT availability FROM tbl_materials ORDER BY 1"),
            "quantity_kg":  value_range("SELECT MIN(quantity_kg), MAX(quantity_kg) FROM tbl_materials"),
        },
        "coating": {
            "made_by":         distinct("SELECT DISTINCT made_by FROM tbl_coating ORDER BY 1"),
            "coat_weight_gsm": value_range("SELECT MIN(coat_weight_gsm), MAX(coat_weight_gsm) FROM tbl_coating"),
            "porosity":        value_range("SELECT MIN(porosity), MAX(porosity) FROM tbl_coating"),
        },
        "cell": {
            "made_by":            cells_made_by,
            "electrolyte":        cells_electrolyte,
            "formation_capacity": cell_capacity,
            "np_ratio":           value_range("SELECT MIN(np_ratio), MAX(np_ratio) FROM tbl_slp"),
        },
    }
    cur.close()
    conn.close()
    return result
