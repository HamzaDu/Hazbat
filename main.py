from fastapi import FastAPI
import psycopg2
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

def get_connection():
    return psycopg2.connect(dbname="bmac", user="hazma", host="localhost")


@app.post("/materials")
def create_material(material_id: str, chemistry: str, supplier: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tbl_materials (material_id, chemistry, supplier) VALUES (%s, %s, %s)",
        (material_id, chemistry, supplier)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "created", "material_id": material_id}

@app.post("/coatings")
def create_coating(coating_id: str, material_id: str, project: str, made_by: str):
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

@app.post("/slp")
def create_slp(slp_id: str, coating_id: str, project: str, made_by: str):
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

@app.post("/coincell")
def create_coincell(coincell_id: str, coating_id: str, project: str, made_by: str):
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

        elif record_type == "coincell":
            cur.execute(
                "SELECT coating_id, project, date_made, made_by, electrolyte, formation_capacity "
                "FROM tbl_coincell WHERE coincell_id = %s",
                (record_id,)
            )
            columns = ["coating_id", "project", "date_made", "made_by", "electrolyte", "formation_capacity"]

        elif record_type == "mlp":
            cur.execute(
                "SELECT cat_coating_id, an_coating_id, project, date_made, cell_capacity "
                "FROM tbl_mlp WHERE mlp_id = %s",
                (record_id,)
            )
            columns = ["cat_coating_id", "an_coating_id", "project", "date_made", "cell_capacity"]

        else:
            columns = []

        if record_type and record_type != "coating":
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