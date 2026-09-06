from fastapi import FastAPI, Request, Form
import psycopg2
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse

app = FastAPI()
templates = Jinja2Templates(directory="templates")

def get_connection():
    return psycopg2.connect(dbname="bmac", user="hazma", host="localhost")

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/materials/new", response_class=HTMLResponse)
def new_material_form(request: Request):
    return templates.TemplateResponse("new_material.html", {"request": request})
    
@app.post("/materials/new", response_class=HTMLResponse)
def submit_material_form(request: Request, material_id: str = Form(...), chemistry: str = Form(...), supplier: str = Form(...)):
    material_id = material_id.strip()
    chemistry = chemistry.strip()
    supplier = supplier.strip()

    error = None
    success = None

    if not material_id or not chemistry or not supplier:
        error = "All fields are required and cannot be blank."
    elif material_id != material_id.upper():
        error = f"Material ID must be uppercase. Try: {material_id.upper()}"
    elif not (material_id.startswith("CAT-") or material_id.startswith("AN-")):
        error = "Material ID must start with 'CAT-' or 'AN-'."
    else:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO tbl_materials (material_id, chemistry, supplier) VALUES (%s, %s, %s)",
                (material_id, chemistry, supplier)
            )
            conn.commit()
            success = material_id
        except Exception as e:
            conn.rollback()
            error = str(e)
        cur.close()
        conn.close()

    return templates.TemplateResponse("new_material.html", {"request": request, "error": error, "success": success})

@app.post("/materials")
def create_material(material_id: str, chemistry: str, supplier: str):
    material_id = material_id.strip()
    chemistry = chemistry.strip()
    supplier = supplier.strip()

    if not material_id or not chemistry or not supplier:
        return {"status": "error", "detail": "All fields are required and cannot be blank."}

    if material_id != material_id.upper():
        return {"status": "error", "detail": f"Material ID must be uppercase. Try: {material_id.upper()}"}

    if not (material_id.startswith("CAT-") or material_id.startswith("AN-")):
        return {"status": "error", "detail": "Material ID must start with 'CAT-' or 'AN-'."}

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO tbl_materials (material_id, chemistry, supplier) VALUES (%s, %s, %s)",
            (material_id, chemistry, supplier)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return {"status": "error", "detail": str(e)}
    cur.close()
    conn.close()
    return {"status": "created", "material_id": material_id}

@app.post("/coatings")
def create_coating(coating_id: str, material_id: str, project: str, made_by: str):
    coating_id = coating_id.strip()
    material_id = material_id.strip()
    project = project.strip()
    made_by = made_by.strip()

    if not coating_id or not material_id or not project or not made_by:
        return {"status": "error", "detail": "All fields are required and cannot be blank."}

    if coating_id != coating_id.upper():
        return {"status": "error", "detail": f"Coating ID must be uppercase. Try: {coating_id.upper()}"}

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO tbl_coating (coating_id, material_id, project, made_by) VALUES (%s, %s, %s, %s)",
            (coating_id, material_id, project, made_by)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return {"status": "error", "detail": str(e)}
    cur.close()
    conn.close()
    return {"status": "created", "coating_id": coating_id}

@app.get("/coatings/new", response_class=HTMLResponse)
def new_coating_form(request: Request):
    return templates.TemplateResponse("new_coating.html", {"request": request})


@app.post("/coatings/new", response_class=HTMLResponse)
def submit_coating_form(request: Request, coating_id: str = Form(...), material_id: str = Form(...), project: str = Form(...), made_by: str = Form(...)):
    coating_id = coating_id.strip()
    material_id = material_id.strip()
    project = project.strip()
    made_by = made_by.strip()

    error = None
    success = None

    if not coating_id or not material_id or not project or not made_by:
        error = "All fields are required and cannot be blank."
    elif coating_id != coating_id.upper():
        error = f"Coating ID must be uppercase. Try: {coating_id.upper()}"
    else:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO tbl_coating (coating_id, material_id, project, made_by) VALUES (%s, %s, %s, %s)",
                (coating_id, material_id, project, made_by)
            )
            conn.commit()
            success = coating_id
        except Exception as e:
            conn.rollback()
            error = str(e)
        cur.close()
        conn.close()

    return templates.TemplateResponse("new_coating.html", {"request": request, "error": error, "success": success})

@app.post("/slp")
def create_slp(slp_id: str, coating_id: str, project: str, made_by: str):
    slp_id = slp_id.strip()
    coating_id = coating_id.strip()
    project = project.strip()
    made_by = made_by.strip()

    if not slp_id or not coating_id or not project or not made_by:
        return {"status": "error", "detail": "All fields are required and cannot be blank."}

    if slp_id != slp_id.upper():
        return {"status": "error", "detail": f"SLP ID must be uppercase. Try: {slp_id.upper()}"}

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO tbl_slp (slp_id, coating_id, project, made_by) VALUES (%s, %s, %s, %s)",
            (slp_id, coating_id, project, made_by)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return {"status": "error", "detail": str(e)}
    cur.close()
    conn.close()
    return {"status": "created", "slp_id": slp_id}
@app.get("/slp/new", response_class=HTMLResponse)
def new_slp_form(request: Request):
    return templates.TemplateResponse("new_slp.html", {"request": request})


@app.post("/slp/new", response_class=HTMLResponse)
def submit_slp_form(request: Request, slp_id: str = Form(...), coating_id: str = Form(...), project: str = Form(...), made_by: str = Form(...), formation_capacity: str = Form(None)):
    slp_id = slp_id.strip()
    coating_id = coating_id.strip()
    project = project.strip()
    made_by = made_by.strip()

    error = None
    success = None

    if not slp_id or not coating_id or not project or not made_by:
        error = "All fields are required and cannot be blank."
    elif slp_id != slp_id.upper():
        error = f"SLP ID must be uppercase. Try: {slp_id.upper()}"
    else:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO tbl_slp (slp_id, coating_id, project, made_by, formation_capacity) VALUES (%s, %s, %s, %s, %s)",
                (slp_id, coating_id, project, made_by, formation_capacity if formation_capacity else None)
            )
            conn.commit()
            success = slp_id
        except Exception as e:
            conn.rollback()
            error = str(e)
        cur.close()
        conn.close()

    return templates.TemplateResponse("new_slp.html", {"request": request, "error": error, "success": success})

@app.post("/coincell")
def create_coincell(coincell_id: str, coating_id: str, project: str, made_by: str):
    coincell_id = coincell_id.strip()
    coating_id = coating_id.strip()
    project = project.strip()
    made_by = made_by.strip()

    if not coincell_id or not coating_id or not project or not made_by:
        return {"status": "error", "detail": "All fields are required and cannot be blank."}

    if coincell_id != coincell_id.upper():
        return {"status": "error", "detail": f"CoinCell ID must be uppercase. Try: {coincell_id.upper()}"}

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO tbl_coincell (coincell_id, coating_id, project, made_by) VALUES (%s, %s, %s, %s)",
            (coincell_id, coating_id, project, made_by)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return {"status": "error", "detail": str(e)}
    cur.close()
    conn.close()
    return {"status": "created", "coincell_id": coincell_id}

@app.get("/coincell/new", response_class=HTMLResponse)
def new_coincell_form(request: Request):
    return templates.TemplateResponse("new_coincell.html", {"request": request})


@app.post("/coincell/new", response_class=HTMLResponse)
def submit_coincell_form(request: Request, coincell_id: str = Form(...), coating_id: str = Form(...), project: str = Form(...), made_by: str = Form(...)):
    coincell_id = coincell_id.strip()
    coating_id = coating_id.strip()
    project = project.strip()
    made_by = made_by.strip()

    error = None
    success = None

    if not coincell_id or not coating_id or not project or not made_by:
        error = "All fields are required and cannot be blank."
    elif coincell_id != coincell_id.upper():
        error = f"Coin Cell ID must be uppercase. Try: {coincell_id.upper()}"
    else:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO tbl_coincell (coincell_id, coating_id, project, made_by) VALUES (%s, %s, %s, %s)",
                (coincell_id, coating_id, project, made_by)
            )
            conn.commit()
            success = coincell_id
        except Exception as e:
            conn.rollback()
            error = str(e)
        cur.close()
        conn.close()

    return templates.TemplateResponse("new_coincell.html", {"request": request, "error": error, "success": success})

@app.post("/mlp")
def create_mlp(mlp_id: str, cat_coating_id: str, an_coating_id: str, project: str):
    mlp_id = mlp_id.strip()
    cat_coating_id = cat_coating_id.strip()
    an_coating_id = an_coating_id.strip()
    project = project.strip()

    if not mlp_id or not cat_coating_id or not an_coating_id or not project:
        return {"status": "error", "detail": "All fields are required and cannot be blank."}

    if mlp_id != mlp_id.upper():
        return {"status": "error", "detail": f"MLP ID must be uppercase. Try: {mlp_id.upper()}"}

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO tbl_mlp (mlp_id, cat_coating_id, an_coating_id, project) VALUES (%s, %s, %s, %s)",
            (mlp_id, cat_coating_id, an_coating_id, project)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return {"status": "error", "detail": str(e)}
    cur.close()
    conn.close()
    return {"status": "created", "mlp_id": mlp_id}
@app.get("/mlp/new", response_class=HTMLResponse)
def new_mlp_form(request: Request):
    return templates.TemplateResponse("new_mlp.html", {"request": request})


@app.post("/mlp/new", response_class=HTMLResponse)
def submit_mlp_form(request: Request, mlp_id: str = Form(...), cat_coating_id: str = Form(...), an_coating_id: str = Form(...), project: str = Form(...)):
    mlp_id = mlp_id.strip()
    cat_coating_id = cat_coating_id.strip()
    an_coating_id = an_coating_id.strip()
    project = project.strip()

    error = None
    success = None

    if not mlp_id or not cat_coating_id or not an_coating_id or not project:
        error = "All fields are required and cannot be blank."
    elif mlp_id != mlp_id.upper():
        error = f"MLP ID must be uppercase. Try: {mlp_id.upper()}"
    else:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO tbl_mlp (mlp_id, cat_coating_id, an_coating_id, project) VALUES (%s, %s, %s, %s)",
                (mlp_id, cat_coating_id, an_coating_id, project)
            )
            conn.commit()
            success = mlp_id
        except Exception as e:
            conn.rollback()
            error = str(e)
        cur.close()
        conn.close()

    return templates.TemplateResponse("new_mlp.html", {"request": request, "error": error, "success": success})

@app.get("/directory", response_class=HTMLResponse)
def directory(request: Request, record_id: str = None):
    record = None
    record_type = None
    searched = record_id is not None

    if record_id:
        record_type = detect_record_type(record_id)
        conn = get_connection()
        cur = conn.cursor()

        if record_type == "material":
            cur.execute(
                "SELECT chemistry, supplier, date_received, quantity_kg, location, availability "
                "FROM tbl_materials WHERE material_id = %s",
                (record_id,)
            )
            columns = ["chemistry", "supplier", "date_received", "quantity_kg", "location", "availability"]
            row = cur.fetchone()
            if row:
                record = dict(zip(columns, row))
                cur.execute("SELECT coating_id FROM tbl_coating WHERE material_id = %s", (record_id,))
                downstream = [f"Coating: {r[0]}" for r in cur.fetchall()]
                record["_chain"] = downstream if downstream else ["No downstream records yet"]

        elif record_type == "coating":
            cur.execute(
                "SELECT material_id, project, coating_date, made_by, coat_weight_gsm, porosity "
                "FROM tbl_coating WHERE coating_id = %s",
                (record_id,)
            )
            columns = ["material_id", "project", "coating_date", "made_by", "coat_weight_gsm", "porosity"]
            row = cur.fetchone()
            if row:
                record = dict(zip(columns, row))

                cur.execute("SELECT chemistry FROM tbl_materials WHERE material_id = %s", (record["material_id"],))
                mat = cur.fetchone()
                upstream = [f"Material: {record['material_id']} ({mat[0] if mat else '?'})"]

                downstream = []
                cur.execute("SELECT slp_id FROM tbl_slp WHERE coating_id = %s", (record_id,))
                downstream += [f"SLP: {r[0]}" for r in cur.fetchall()]
                cur.execute("SELECT coincell_id FROM tbl_coincell WHERE coating_id = %s", (record_id,))
                downstream += [f"CoinCell: {r[0]}" for r in cur.fetchall()]
                cur.execute("SELECT mlp_id FROM tbl_mlp WHERE cat_coating_id = %s OR an_coating_id = %s", (record_id, record_id))
                downstream += [f"MLP: {r[0]}" for r in cur.fetchall()]

                record["_chain"] = upstream + (downstream if downstream else ["No downstream records yet"])

        elif record_type == "slp":
            cur.execute(
                "SELECT coating_id, project, date_made, made_by, electrolyte, formation_capacity "
                "FROM tbl_slp WHERE slp_id = %s",
                (record_id,)
            )
            columns = ["coating_id", "project", "date_made", "made_by", "electrolyte", "formation_capacity"]
            row = cur.fetchone()
            if row:
                record = dict(zip(columns, row))
                cur.execute("SELECT material_id FROM tbl_coating WHERE coating_id = %s", (record["coating_id"],))
                mat = cur.fetchone()
                record["_chain"] = [f"Coating: {record['coating_id']}", f"Material: {mat[0] if mat else '?'}"]


        elif record_type == "coincell":
            cur.execute(
                "SELECT coating_id, project, date_made, made_by, electrolyte, formation_capacity "
                "FROM tbl_coincell WHERE coincell_id = %s",
                (record_id,)
            )
            columns = ["coating_id", "project", "date_made", "made_by", "electrolyte", "formation_capacity"]
            row = cur.fetchone()
            if row:
                record = dict(zip(columns, row))
                cur.execute("SELECT material_id FROM tbl_coating WHERE coating_id = %s", (record["coating_id"],))
                mat = cur.fetchone()
                record["_chain"] = [f"Coating: {record['coating_id']}", f"Material: {mat[0] if mat else '?'}"]

        elif record_type == "mlp":
            cur.execute(
                "SELECT cat_coating_id, an_coating_id, project, date_made, cell_capacity "
                "FROM tbl_mlp WHERE mlp_id = %s",
                (record_id,)
            )
            columns = ["cat_coating_id", "an_coating_id", "project", "date_made", "cell_capacity"]
            row = cur.fetchone()
            if row:
                record = dict(zip(columns, row))
                chain = []
                for label, cid in (("Cathode coating", record["cat_coating_id"]), ("Anode coating", record["an_coating_id"])):
                    cur.execute("SELECT material_id FROM tbl_coating WHERE coating_id = %s", (cid,))
                    mat = cur.fetchone()
                    chain.append(f"{label}: {cid} (material: {mat[0] if mat else '?'})")
                record["_chain"] = chain

        else:
            columns = []

        if record_type and record_type not in ("coating", "material", "slp", "coincell", "mlp"):
            row = cur.fetchone()
            if row:
                record = dict(zip(columns, row))

        cur.close()
        conn.close()

    return templates.TemplateResponse(
        "search.html",
        {"request": request, "record": record, "record_id": record_id, "record_type": record_type, "searched": searched}
    )

def detect_record_type(record_id: str) -> str:
    rid = record_id.upper()
    if "-SLP-" in rid:
        return "slp"
    if "MLP-" in rid:
        return "mlp"
    if "-CC-" in rid:
        return "coincell"
    if "-C0" in rid or "-C1" in rid:
        return "coating"
    if rid.startswith("CAT") or rid.startswith("AN"):
        return "material"
    return None

@app.get("/inventory/materials", response_class=HTMLResponse)
def inventory_materials(request: Request):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT material_id, chemistry, supplier, date_received, quantity_kg, location, availability "
        "FROM tbl_materials ORDER BY material_id"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    columns = ["Material ID", "Chemistry", "Supplier", "Date Received", "Quantity (kg)", "Location", "Availability"]
    return templates.TemplateResponse(
        "inventory.html",
        {"request": request, "title": "Materials", "columns": columns, "rows": rows}
    )

@app.get("/inventory/coatings", response_class=HTMLResponse)
def inventory_coatings(request: Request):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT coating_id, material_id, project, coating_date, made_by, coat_weight_gsm, porosity "
        "FROM tbl_coating ORDER BY coating_id"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    columns = ["Coating ID", "Material ID", "Project", "Coating Date", "Made By", "GSM", "Porosity"]
    return templates.TemplateResponse("inventory.html", {"request": request, "title": "Coatings", "columns": columns, "rows": rows})


@app.get("/inventory/slp", response_class=HTMLResponse)
def inventory_slp(request: Request):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT slp_id, coating_id, project, date_made, made_by, electrolyte, formation_capacity "
        "FROM tbl_slp ORDER BY slp_id"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    columns = ["SLP ID", "Coating ID", "Project", "Date Made", "Made By", "Electrolyte", "Formation Capacity"]
    return templates.TemplateResponse("inventory.html", {"request": request, "title": "SLP Cells", "columns": columns, "rows": rows})


@app.get("/inventory/coincell", response_class=HTMLResponse)
def inventory_coincell(request: Request):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT coincell_id, coating_id, project, date_made, made_by, electrolyte, formation_capacity "
        "FROM tbl_coincell ORDER BY coincell_id"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    columns = ["Coin Cell ID", "Coating ID", "Project", "Date Made", "Made By", "Electrolyte", "Formation Capacity"]
    return templates.TemplateResponse("inventory.html", {"request": request, "title": "Coin Cells", "columns": columns, "rows": rows})


@app.get("/inventory/mlp", response_class=HTMLResponse)
def inventory_mlp(request: Request):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT mlp_id, cat_coating_id, an_coating_id, project, date_made, cell_capacity "
        "FROM tbl_mlp ORDER BY mlp_id"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    columns = ["MLP ID", "Cathode Coating", "Anode Coating", "Project", "Date Made", "Cell Capacity"]
    return templates.TemplateResponse("inventory.html", {"request": request, "title": "MLP Cells", "columns": columns, "rows": rows})

@app.get("/api/chart/formation-capacity")
def chart_formation_capacity():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT slp_id, formation_capacity FROM tbl_slp WHERE formation_capacity IS NOT NULL ORDER BY slp_id")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    labels = [r[0] for r in rows]
    values = [float(r[1]) for r in rows]
    return JSONResponse({"labels": labels, "values": values})

@app.get("/chart/formation-capacity", response_class=HTMLResponse)
def formation_capacity_page(request: Request):
    return templates.TemplateResponse("chart.html", {"request": request})