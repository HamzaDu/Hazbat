from fastapi import FastAPI, Request, Form
import psycopg2
import bcrypt
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from HAZbot import ask_ai_for_sql
import pandas as pd
from fastapi import UploadFile, File
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import RedirectResponse
import qrcode
import io
import base64
import os
import re
from datetime import datetime
 
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "dev-secret-change-this-later"))
templates = Jinja2Templates(directory="templates")
def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)
    return psycopg2.connect(dbname="bmac", user="hazma", host="localhost")
 
def require_login(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/login", status_code=303)
    return None
 
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})
 
@app.get("/materials/new", response_class=HTMLResponse)
def new_material_form(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("new_material.html", {"request": request})
 
# --- Shared helpers for the "New record" forms ------------------------------
FIELD_LABELS = {
    "quantity_kg": "Quantity (kg)", "coat_weight_gsm": "Coat weight (g/m²)", "porosity": "Porosity",
    "formation_capacity": "Formation capacity", "np_ratio": "N/P ratio",
    "cell_capacity": "Cell capacity", "ac_area_ratio": "A/C area ratio", "gsm": "GSM",
}


def clean_optional_fields(values: dict, numeric_fields=()):
    """Tidy optional form values: blank -> None, numbers -> float.
    Returns (cleaned_dict, None) or (None, error_message)."""
    cleaned = {}
    for field, value in values.items():
        value = (value or "").strip()
        if value == "":
            cleaned[field] = None
        elif field in numeric_fields:
            label = FIELD_LABELS.get(field, field)
            try:
                number = float(value)
            except ValueError:
                return None, f"{label} must be a number."
            if number < 0:
                return None, f"{label} cannot be negative."
            cleaned[field] = number
        else:
            cleaned[field] = value
    return cleaned, None


def insert_record(table: str, data: dict):
    """INSERT one row. Table/column names come from our own code, never from the user.
    Returns None on success or an error message."""
    columns = ", ".join(data.keys())
    placeholders = ", ".join(["%s"] * len(data))
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", list(data.values()))
        conn.commit()
        return None
    except Exception as e:
        conn.rollback()
        return str(e)
    finally:
        cur.close()
        conn.close()


def form_state(*dicts):
    """Values to re-fill the form with if saving fails, so nothing has to be retyped."""
    merged = {}
    for d in dicts:
        merged.update({k: (v or "").strip() for k, v in d.items()})
    return merged


def record_exists(table: str, id_column: str, value: str) -> bool:
    """True if a row with this ID exists. Table/column names come from our own code."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT 1 FROM {table} WHERE {id_column} = %s", (value,))
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()


def coating_electrode(coating_id: str):
    """'cathode' / 'anode' for a coating (from its material's CAT-/AN- prefix), or None if not found."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT material_id FROM tbl_coating WHERE coating_id = %s", (coating_id,))
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    if not row:
        return None
    return "cathode" if row[0].startswith("CAT-") else "anode" if row[0].startswith("AN-") else "unknown"


def load_form_options():
    """Lists that fill the dropdowns on the New Coating / SLP / Coin Cell / MLP forms."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT project_name FROM tbl_projects WHERE active ORDER BY project_name")
        projects = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT material_id, chemistry, supplier FROM tbl_materials ORDER BY material_id")
        materials = [{"id": r[0], "label": " · ".join(str(x) for x in r[1:] if x)} for r in cur.fetchall()]

        cur.execute(
            "SELECT c.coating_id, c.material_id, m.chemistry, c.coating_date "
            "FROM tbl_coating c LEFT JOIN tbl_materials m ON m.material_id = c.material_id "
            "ORDER BY c.coating_id"
        )
        coatings = []
        for coating_id, material_id, chemistry, coating_date in cur.fetchall():
            label = " · ".join(str(x) for x in (chemistry or material_id, coating_date) if x)
            electrode = "cathode" if material_id.startswith("CAT-") else "anode" if material_id.startswith("AN-") else ""
            coatings.append({"id": coating_id, "label": label, "electrode": electrode})
    finally:
        cur.close()
        conn.close()

    return {
        "projects": projects,
        "materials": materials,
        "coatings": coatings,
        "cat_coatings": [c for c in coatings if c["electrode"] == "cathode"],
        "an_coatings": [c for c in coatings if c["electrode"] == "anode"],
    }


# --- Bulk upload helpers -----------------------------------------------------
# Cells that mean "no data". Stored as NULL in the database and shown as "—" on every page.
BLANK_MARKERS = {"", "nan", "nat", "none", "null", "n/a", "na", "-", "—", "–"}
DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y")

# Required + optional columns for each table's bulk upload. "aliases" lets older
# spreadsheets keep working (e.g. a "GSM" column on the coatings sheet).
BULK_SPECS = {
    "tbl_materials": {"id": "material_id", "required": ["material_id", "chemistry", "supplier"],
                      "numeric": ["quantity_kg"], "dates": ["date_received"],
                      "text": ["location", "availability", "notes"], "aliases": {}},
    "tbl_coating":   {"id": "coating_id", "required": ["coating_id", "material_id", "project", "made_by"],
                      "numeric": ["coat_weight_gsm", "porosity"], "dates": ["coating_date"],
                      "text": ["notes"], "aliases": {"gsm": "coat_weight_gsm", "coat_weight": "coat_weight_gsm", "coat_weight_g_m": "coat_weight_gsm", "gsm_g_m": "coat_weight_gsm"}},
    "tbl_slp":       {"id": "slp_id", "required": ["slp_id", "coating_id", "project", "made_by"],
                      "numeric": ["formation_capacity", "np_ratio"], "dates": ["date_made"],
                      "text": ["electrolyte", "notes"], "aliases": {"n_p_ratio": "np_ratio", "formation_capacity_mah": "formation_capacity"}},
    "tbl_coincell":  {"id": "coincell_id", "required": ["coincell_id", "coating_id", "project", "made_by"],
                      "numeric": ["formation_capacity", "gsm"], "dates": ["date_made"],
                      "text": ["electrolyte", "cell_type", "notes"], "aliases": {"gsm_g_m": "gsm", "formation_capacity_mah": "formation_capacity"}},
    "tbl_mlp":       {"id": "mlp_id", "required": ["mlp_id", "cat_coating_id", "an_coating_id", "project"],
                      "numeric": ["cell_capacity", "ac_area_ratio"], "dates": ["date_made"],
                      "text": ["electrolyte"], "aliases": {"a_c_area_ratio": "ac_area_ratio"}},
}


def normalise_header(name) -> str:
    """'Material ID ' / 'material-id' / 'Quantity (kg)' -> 'material_id' / 'material_id' / 'quantity_kg'."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def clean_cell(value):
    """Tidy one spreadsheet cell; N/A, -, blank etc. become None."""
    if value is None:
        return None
    value = str(value).strip()
    return None if value.lower() in BLANK_MARKERS else value


def parse_date(value: str) -> str:
    """Accepts 2026-09-24 or 24/09/2026 (UK day-first) etc.; returns ISO YYYY-MM-DD."""
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"'{value}' is not a valid date (use YYYY-MM-DD or DD/MM/YYYY).")


def read_upload(contents: bytes, filename: str):
    """Read a CSV/Excel upload as text so nothing is silently converted. Returns a list of row dicts."""
    buffer = io.BytesIO(contents)
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(buffer, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(buffer, dtype=str)
    return df.to_dict("records")


def process_bulk_upload(rows, table: str, check=None):
    """Validate and insert each row. check(values) may return an error message for a row.
    Returns {"success": [...ids], "failed": [{"row", "reason"}], "ignored": [...unknown columns]}."""
    spec = BULK_SPECS[table]
    known = spec["required"] + spec["numeric"] + spec["dates"] + spec["text"]
    success, failed, ignored = [], [], set()

    for i, raw in enumerate(rows):
        row_num = i + 2  # +2 = header row + 1-based numbering, matching the spreadsheet
        values = {}
        for header, cell in raw.items():
            key = normalise_header(header)
            key = spec["aliases"].get(key, key)
            if key in known:
                values[key] = clean_cell(cell)
            elif key and not key.startswith("unnamed"):
                ignored.add(str(header).strip())

        if all(values.get(k) is None for k in known):
            continue  # completely empty row, e.g. trailing blank lines in Excel

        missing = [k for k in spec["required"] if not values.get(k)]
        if missing:
            failed.append({"row": row_num, "reason": f"Missing required field(s): {', '.join(missing)}."})
            continue

        record_id = values[spec["id"]]
        if record_id != record_id.upper():
            failed.append({"row": row_num, "reason": f"'{record_id}' is not uppercase."})
            continue

        error = check(values) if check else None
        if error:
            failed.append({"row": row_num, "reason": error})
            continue

        try:
            for field in spec["dates"]:
                if values.get(field):
                    values[field] = parse_date(values[field])
        except ValueError as e:
            failed.append({"row": row_num, "reason": str(e)})
            continue

        optional = {k: values.get(k) for k in spec["numeric"] + spec["dates"] + spec["text"]}
        extras, error = clean_optional_fields(optional, numeric_fields=set(spec["numeric"]))
        if error:
            failed.append({"row": row_num, "reason": error})
            continue

        error = insert_record(table, {**{k: values[k] for k in spec["required"]}, **extras})
        if error:
            failed.append({"row": row_num, "reason": error})
        else:
            success.append(record_id)

    return {"success": success, "failed": failed, "ignored": sorted(ignored)}


def check_material_row(v):
    if not (v["material_id"].startswith("CAT-") or v["material_id"].startswith("AN-")):
        return f"'{v['material_id']}' must start with CAT- or AN-."


def check_coating_row(v):
    if not record_exists("tbl_materials", "material_id", v["material_id"]):
        return f"Material {v['material_id']} doesn't exist."


def check_cell_row(v):
    if not record_exists("tbl_coating", "coating_id", v["coating_id"]):
        return f"Coating {v['coating_id']} doesn't exist."


def check_mlp_row(v):
    if coating_electrode(v["cat_coating_id"]) != "cathode":
        return f"{v['cat_coating_id']} isn't an existing cathode (CAT-) coating."
    if coating_electrode(v["an_coating_id"]) != "anode":
        return f"{v['an_coating_id']} isn't an existing anode (AN-) coating."


@app.post("/materials/new", response_class=HTMLResponse)
def submit_material_form(request: Request, material_id: str = Form(...), chemistry: str = Form(...), supplier: str = Form(...),
                         date_received: str = Form(None), quantity_kg: str = Form(None), location: str = Form(None),
                         availability: str = Form(None), notes: str = Form(None)):
    redirect = require_login(request)
    if redirect:
        return redirect
    required = {"material_id": material_id.strip(), "chemistry": chemistry.strip(), "supplier": supplier.strip()}
    optional = {"date_received": date_received, "quantity_kg": quantity_kg, "location": location,
                "availability": availability, "notes": notes}
    form = form_state(required, optional)
    error = None
    success = None

    material_id = required["material_id"]
    if not all(required.values()):
        error = "Material ID, chemistry and supplier are required."
    elif material_id != material_id.upper():
        error = f"Material ID must be uppercase. Try: {material_id.upper()}"
    elif not (material_id.startswith("CAT-") or material_id.startswith("AN-")):
        error = "Material ID must start with 'CAT-' or 'AN-'."
    else:
        extras, error = clean_optional_fields(optional, numeric_fields={"quantity_kg"})
        if not error:
            error = insert_record("tbl_materials", {**required, **extras})
        if not error:
            success, form = material_id, {}

    return templates.TemplateResponse("new_material.html", {"request": request, "error": error, "success": success, "form": form})

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
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("new_coating.html", {"request": request, **load_form_options()})
 
 
@app.post("/coatings/new", response_class=HTMLResponse)
def submit_coating_form(request: Request, coating_id: str = Form(...), material_id: str = Form(...), project: str = Form(...), made_by: str = Form(...),
                        coating_date: str = Form(None), coat_weight_gsm: str = Form(None), porosity: str = Form(None), notes: str = Form(None)):
    redirect = require_login(request)
    if redirect:
        return redirect
    required = {"coating_id": coating_id.strip(), "material_id": material_id.strip(), "project": project.strip(), "made_by": made_by.strip()}
    optional = {"coating_date": coating_date, "coat_weight_gsm": coat_weight_gsm, "porosity": porosity, "notes": notes}
    form = form_state(required, optional)
    error = None
    success = None

    coating_id = required["coating_id"]
    if not all(required.values()):
        error = "Coating ID, material ID, project and made by are required."
    elif coating_id != coating_id.upper():
        error = f"Coating ID must be uppercase. Try: {coating_id.upper()}"
    elif not record_exists("tbl_materials", "material_id", required["material_id"]):
        error = f"Material {required['material_id']} doesn't exist yet. Pick one from the list or create it first."
    else:
        extras, error = clean_optional_fields(optional, numeric_fields={"coat_weight_gsm", "porosity"})
        if not error:
            error = insert_record("tbl_coating", {**required, **extras})
        if not error:
            success, form = coating_id, {}

    return templates.TemplateResponse("new_coating.html", {"request": request, "error": error, "success": success, "form": form, **load_form_options()})

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
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("new_slp.html", {"request": request, **load_form_options()})
 
@app.post("/slp/new", response_class=HTMLResponse)
def submit_slp_form(request: Request, slp_id: str = Form(...), coating_id: str = Form(...), project: str = Form(...), made_by: str = Form(...),
                    formation_capacity: str = Form(None), date_made: str = Form(None), electrolyte: str = Form(None),
                    np_ratio: str = Form(None), notes: str = Form(None)):
    redirect = require_login(request)
    if redirect:
        return redirect
    required = {"slp_id": slp_id.strip(), "coating_id": coating_id.strip(), "project": project.strip(), "made_by": made_by.strip()}
    optional = {"date_made": date_made, "electrolyte": electrolyte, "formation_capacity": formation_capacity,
                "np_ratio": np_ratio, "notes": notes}
    form = form_state(required, optional)
    error = None
    success = None

    slp_id = required["slp_id"]
    if not all(required.values()):
        error = "SLP ID, coating ID, project and made by are required."
    elif slp_id != slp_id.upper():
        error = f"SLP ID must be uppercase. Try: {slp_id.upper()}"
    elif not record_exists("tbl_coating", "coating_id", required["coating_id"]):
        error = f"Coating {required['coating_id']} doesn't exist yet. Pick one from the list or create it first."
    else:
        extras, error = clean_optional_fields(optional, numeric_fields={"formation_capacity", "np_ratio"})
        if not error:
            error = insert_record("tbl_slp", {**required, **extras})
        if not error:
            success, form = slp_id, {}

    return templates.TemplateResponse("new_slp.html", {"request": request, "error": error, "success": success, "form": form, **load_form_options()})

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
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("new_coincell.html", {"request": request, **load_form_options()})
 
 
@app.post("/coincell/new", response_class=HTMLResponse)
def submit_coincell_form(request: Request, coincell_id: str = Form(...), coating_id: str = Form(...), project: str = Form(...), made_by: str = Form(...),
                         date_made: str = Form(None), electrolyte: str = Form(None), formation_capacity: str = Form(None),
                         cell_type: str = Form(None), gsm: str = Form(None), notes: str = Form(None)):
    redirect = require_login(request)
    if redirect:
        return redirect
    required = {"coincell_id": coincell_id.strip(), "coating_id": coating_id.strip(), "project": project.strip(), "made_by": made_by.strip()}
    optional = {"date_made": date_made, "electrolyte": electrolyte, "formation_capacity": formation_capacity,
                "cell_type": cell_type, "gsm": gsm, "notes": notes}
    form = form_state(required, optional)
    error = None
    success = None

    coincell_id = required["coincell_id"]
    if not all(required.values()):
        error = "Coin cell ID, coating ID, project and made by are required."
    elif coincell_id != coincell_id.upper():
        error = f"Coin Cell ID must be uppercase. Try: {coincell_id.upper()}"
    elif not record_exists("tbl_coating", "coating_id", required["coating_id"]):
        error = f"Coating {required['coating_id']} doesn't exist yet. Pick one from the list or create it first."
    else:
        extras, error = clean_optional_fields(optional, numeric_fields={"formation_capacity", "gsm"})
        if not error:
            error = insert_record("tbl_coincell", {**required, **extras})
        if not error:
            success, form = coincell_id, {}

    return templates.TemplateResponse("new_coincell.html", {"request": request, "error": error, "success": success, "form": form, **load_form_options()})

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
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("new_mlp.html", {"request": request, **load_form_options()})
 
 
@app.post("/mlp/new", response_class=HTMLResponse)
def submit_mlp_form(request: Request, mlp_id: str = Form(...), cat_coating_id: str = Form(...), an_coating_id: str = Form(...), project: str = Form(...),
                    date_made: str = Form(None), electrolyte: str = Form(None), cell_capacity: str = Form(None),
                    ac_area_ratio: str = Form(None)):
    redirect = require_login(request)
    if redirect:
        return redirect
    required = {"mlp_id": mlp_id.strip(), "cat_coating_id": cat_coating_id.strip(), "an_coating_id": an_coating_id.strip(), "project": project.strip()}
    optional = {"date_made": date_made, "electrolyte": electrolyte, "cell_capacity": cell_capacity, "ac_area_ratio": ac_area_ratio}
    form = form_state(required, optional)
    error = None
    success = None

    mlp_id = required["mlp_id"]
    if not all(required.values()):
        error = "MLP ID, both coating IDs and project are required."
    elif mlp_id != mlp_id.upper():
        error = f"MLP ID must be uppercase. Try: {mlp_id.upper()}"
    elif coating_electrode(required["cat_coating_id"]) != "cathode":
        error = f"{required['cat_coating_id']} isn't an existing cathode (CAT-) coating."
    elif coating_electrode(required["an_coating_id"]) != "anode":
        error = f"{required['an_coating_id']} isn't an existing anode (AN-) coating."
    else:
        extras, error = clean_optional_fields(optional, numeric_fields={"cell_capacity", "ac_area_ratio"})
        if not error:
            error = insert_record("tbl_mlp", {**required, **extras})
        if not error:
            success, form = mlp_id, {}

    return templates.TemplateResponse("new_mlp.html", {"request": request, "error": error, "success": success, "form": form, **load_form_options()})

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
                "SELECT chemistry, supplier, date_received, quantity_kg, location, availability, notes "
                "FROM tbl_materials WHERE material_id = %s",
                (record_id,)
            )
            columns = ["chemistry", "supplier", "date_received", "quantity_kg", "location", "availability", "notes"]
            row = cur.fetchone()
            if row:
                record = dict(zip(columns, row))
                cur.execute("SELECT coating_id FROM tbl_coating WHERE material_id = %s", (record_id,))
                downstream = [f"Coating: {r[0]}" for r in cur.fetchall()]
                record["_chain"] = downstream if downstream else ["No downstream records yet"]
 
        elif record_type == "coating":
            cur.execute(
                "SELECT material_id, project, coating_date, made_by, coat_weight_gsm, porosity, notes "
                "FROM tbl_coating WHERE coating_id = %s",
                (record_id,)
            )
            columns = ["material_id", "project", "coating_date", "made_by", "coat_weight_gsm", "porosity", "notes"]
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
                "SELECT coating_id, project, date_made, made_by, electrolyte, formation_capacity, np_ratio, notes "
                "FROM tbl_slp WHERE slp_id = %s",
                (record_id,)
            )
            columns = ["coating_id", "project", "date_made", "made_by", "electrolyte", "formation_capacity", "np_ratio", "notes"]
            row = cur.fetchone()
            if row:
                record = dict(zip(columns, row))
                cur.execute("SELECT material_id FROM tbl_coating WHERE coating_id = %s", (record["coating_id"],))
                mat = cur.fetchone()
                record["_chain"] = [f"Coating: {record['coating_id']}", f"Material: {mat[0] if mat else '?'}"]
 
        elif record_type == "coincell":
            cur.execute(
                "SELECT coating_id, project, date_made, made_by, electrolyte, formation_capacity, cell_type, gsm, notes "
                "FROM tbl_coincell WHERE coincell_id = %s",
                (record_id,)
            )
            columns = ["coating_id", "project", "date_made", "made_by", "electrolyte", "formation_capacity", "cell_type", "gsm", "notes"]
            row = cur.fetchone()
            if row:
                record = dict(zip(columns, row))
                cur.execute("SELECT material_id FROM tbl_coating WHERE coating_id = %s", (record["coating_id"],))
                mat = cur.fetchone()
                record["_chain"] = [f"Coating: {record['coating_id']}", f"Material: {mat[0] if mat else '?'}"]
 
        elif record_type == "mlp":
            cur.execute(
                "SELECT cat_coating_id, an_coating_id, project, date_made, cell_capacity, electrolyte, ac_area_ratio "
                "FROM tbl_mlp WHERE mlp_id = %s",
                (record_id,)
            )
            columns = ["cat_coating_id", "an_coating_id", "project", "date_made", "cell_capacity", "electrolyte", "ac_area_ratio"]
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
    if "-CC" in rid:
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
        {"request": request, "title": "Materials", "columns": columns, "rows": rows,
         "new_url": "/materials/new", "bulk_url": "/materials/bulk-upload"}
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
    return templates.TemplateResponse(
        "inventory.html",
        {"request": request, "title": "Coatings", "columns": columns, "rows": rows,
         "new_url": "/coatings/new", "bulk_url": "/coatings/bulk-upload"}
    )
 
 
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
    return templates.TemplateResponse(
        "inventory.html",
        {"request": request, "title": "SLP Cells", "columns": columns, "rows": rows,
         "new_url": "/slp/new", "bulk_url": "/slp/bulk-upload"}
    )
 
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
    return templates.TemplateResponse(
        "inventory.html",
        {"request": request, "title": "Coin Cells", "columns": columns, "rows": rows,
         "new_url": "/coincell/new", "bulk_url": "/coincell/bulk-upload"}
    )
 
 
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
    return templates.TemplateResponse(
        "inventory.html",
        {"request": request, "title": "MLP Cells", "columns": columns, "rows": rows,
         "new_url": "/mlp/new", "bulk_url": "/mlp/bulk-upload"}
    )
 
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
 
@app.get("/chart", response_class=HTMLResponse)
def chart_page(request: Request):
    return templates.TemplateResponse("chart.html", {"request": request})
 
@app.get("/materials/bulk-upload", response_class=HTMLResponse)
def bulk_upload_form(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("bulk_upload.html", {"request": request})
 
 
@app.post("/materials/bulk-upload", response_class=HTMLResponse)
async def bulk_upload_materials(request: Request, file: UploadFile = File(...)):
    redirect = require_login(request)
    if redirect:
        return redirect
    try:
        rows = read_upload(await file.read(), file.filename)
    except Exception as e:
        return templates.TemplateResponse("bulk_upload.html", {"request": request, "upload_error": f"Couldn't read that file: {e}"})
    results = process_bulk_upload(rows, "tbl_materials", check=check_material_row)
    return templates.TemplateResponse("bulk_upload.html", {"request": request, "results": results})
 
@app.get("/coatings/bulk-upload", response_class=HTMLResponse)
def bulk_upload_coating_form(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("bulk_upload_coating.html", {"request": request})
 
 
@app.post("/coatings/bulk-upload", response_class=HTMLResponse)
async def bulk_upload_coatings(request: Request, file: UploadFile = File(...)):
    redirect = require_login(request)
    if redirect:
        return redirect
    try:
        rows = read_upload(await file.read(), file.filename)
    except Exception as e:
        return templates.TemplateResponse("bulk_upload_coating.html", {"request": request, "upload_error": f"Couldn't read that file: {e}"})
    results = process_bulk_upload(rows, "tbl_coating", check=check_coating_row)
    return templates.TemplateResponse("bulk_upload_coating.html", {"request": request, "results": results})
 
@app.get("/slp/bulk-upload", response_class=HTMLResponse)
def bulk_upload_slp_form(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("bulk_upload_slp.html", {"request": request})
 
 
@app.post("/slp/bulk-upload", response_class=HTMLResponse)
async def bulk_upload_slp(request: Request, file: UploadFile = File(...)):
    redirect = require_login(request)
    if redirect:
        return redirect
    try:
        rows = read_upload(await file.read(), file.filename)
    except Exception as e:
        return templates.TemplateResponse("bulk_upload_slp.html", {"request": request, "upload_error": f"Couldn't read that file: {e}"})
    results = process_bulk_upload(rows, "tbl_slp", check=check_cell_row)
    return templates.TemplateResponse("bulk_upload_slp.html", {"request": request, "results": results})
 
@app.get("/coincell/bulk-upload", response_class=HTMLResponse)
def bulk_upload_coincell_form(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("bulk_upload_coincell.html", {"request": request})
 
@app.post("/coincell/bulk-upload", response_class=HTMLResponse)
async def bulk_upload_coincell(request: Request, file: UploadFile = File(...)):
    redirect = require_login(request)
    if redirect:
        return redirect
    try:
        rows = read_upload(await file.read(), file.filename)
    except Exception as e:
        return templates.TemplateResponse("bulk_upload_coincell.html", {"request": request, "upload_error": f"Couldn't read that file: {e}"})
    results = process_bulk_upload(rows, "tbl_coincell", check=check_cell_row)
    return templates.TemplateResponse("bulk_upload_coincell.html", {"request": request, "results": results})
 
@app.get("/mlp/bulk-upload", response_class=HTMLResponse)
def bulk_upload_mlp_form(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("bulk_upload_mlp.html", {"request": request})
 
 
@app.post("/mlp/bulk-upload", response_class=HTMLResponse)
async def bulk_upload_mlp(request: Request, file: UploadFile = File(...)):
    redirect = require_login(request)
    if redirect:
        return redirect
    try:
        rows = read_upload(await file.read(), file.filename)
    except Exception as e:
        return templates.TemplateResponse("bulk_upload_mlp.html", {"request": request, "upload_error": f"Couldn't read that file: {e}"})
    results = process_bulk_upload(rows, "tbl_mlp", check=check_mlp_row)
    return templates.TemplateResponse("bulk_upload_mlp.html", {"request": request, "results": results})
 
@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})
 
 
@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, password_hash, full_name, is_admin FROM tbl_users WHERE username = %s", (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()
 
    if not user or not bcrypt.checkpw(password.encode(), user[1].encode()):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid username or password."})
 
    request.session["user_id"] = user[0]
    request.session["full_name"] = user[2]
    request.session["is_admin"] = user[3]
 
    return RedirectResponse(url="/", status_code=303)
 
 
@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
@app.get("/card/{record_id}", response_class=HTMLResponse)
def view_card(request: Request, record_id: str):
    record_type = detect_record_type(record_id)
    if not record_type:
        return HTMLResponse("Unrecognised ID format.", status_code=404)

    # Generate the QR code for THIS card's own URL
    card_url = f"{BASE_URL}/card/{record_id}"
    qr_img = qrcode.make(card_url)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode()

    conn = get_connection()
    cur = conn.cursor()

    record = None
    chain = []

    if record_type == "material":
        cur.execute(
            "SELECT chemistry, supplier, date_received, quantity_kg, location, availability, notes "
            "FROM tbl_materials WHERE material_id = %s", (record_id,)
        )
        row = cur.fetchone()
        if row:
            columns = ["Chemistry", "Supplier", "Date Received", "Quantity (kg)", "Location", "Availability", "Notes"]
            record = dict(zip(columns, row))
            cur.execute("SELECT coating_id FROM tbl_coating WHERE material_id = %s", (record_id,))
            chain += [f"Coating: {r[0]}" for r in cur.fetchall()]

    elif record_type == "coating":
        cur.execute(
            "SELECT material_id, project, coating_date, made_by, coat_weight_gsm, porosity, notes "
            "FROM tbl_coating WHERE coating_id = %s", (record_id,)
        )
        row = cur.fetchone()
        if row:
            columns = ["Material ID", "Project", "Coating Date", "Made By", "GSM", "Porosity", "Notes"]
            record = dict(zip(columns, row))
            cur.execute("SELECT slp_id FROM tbl_slp WHERE coating_id = %s", (record_id,))
            chain += [f"SLP: {r[0]}" for r in cur.fetchall()]
            cur.execute("SELECT coincell_id FROM tbl_coincell WHERE coating_id = %s", (record_id,))
            chain += [f"CoinCell: {r[0]}" for r in cur.fetchall()]
            cur.execute("SELECT mlp_id FROM tbl_mlp WHERE cat_coating_id = %s OR an_coating_id = %s", (record_id, record_id))
            chain += [f"MLP: {r[0]}" for r in cur.fetchall()]

    elif record_type == "slp":
        cur.execute(
            "SELECT coating_id, project, date_made, made_by, electrolyte, formation_capacity, np_ratio, notes "
            "FROM tbl_slp WHERE slp_id = %s", (record_id,)
        )
        row = cur.fetchone()
        if row:
            columns = ["Coating ID", "Project", "Date Made", "Made By", "Electrolyte", "Formation Capacity", "N/P Ratio", "Notes"]
            record = dict(zip(columns, row))
            chain.append(f"Coating: {record['Coating ID']}")

    elif record_type == "coincell":
        cur.execute("SELECT coating_id, project, date_made, made_by, electrolyte, formation_capacity, gsm, notes, cell_type FROM tbl_coincell WHERE coincell_id = %s", (record_id,))
        row = cur.fetchone()
        if row:
            columns = ["Coating ID", "Project", "Date Made", "Made By", "Electrolyte", "Formation Capacity", "GSM", "Notes", "Cell Type"]
            record = dict(zip(columns, [str(v) if v is not None else "N/A" for v in row]))
            chain = [f"Coating: {record['Coating ID']}"]

    elif record_type == "mlp":
        cur.execute(
            "SELECT cat_coating_id, an_coating_id, project, date_made, cell_capacity, electrolyte, ac_area_ratio "
            "FROM tbl_mlp WHERE mlp_id = %s", (record_id,)
        )
        row = cur.fetchone()
        if row:
            columns = ["Cathode Coating", "Anode Coating", "Project", "Date Made", "Cell Capacity", "Electrolyte", "A/C Area Ratio"]
            record = dict(zip(columns, row))
            chain.append(f"Cathode: {record['Cathode Coating']}")
            chain.append(f"Anode: {record['Anode Coating']}")

    cur.close()
    conn.close()

    if not record:
        return HTMLResponse("Record not found.", status_code=404)

    return templates.TemplateResponse(
        "card.html",
        {"request": request, "record_id": record_id, "record_type": record_type,
         "record": record, "chain": chain, "qr_base64": qr_base64}
    )
@app.get("/api/card/{record_id}")
def card_data(record_id: str):
    record_type = detect_record_type(record_id)
    if not record_type:
        return JSONResponse({"error": "Unrecognised ID format"}, status_code=404)

    conn = get_connection()
    cur = conn.cursor()
    record = None
    chain = []

    if record_type == "material":
        cur.execute("SELECT chemistry, supplier, date_received, quantity_kg, location, availability, notes FROM tbl_materials WHERE material_id = %s", (record_id,))
        row = cur.fetchone()
        if row:
            columns = ["Chemistry", "Supplier", "Date Received", "Quantity (kg)", "Location", "Availability", "Notes"]
            record = dict(zip(columns, [str(v) if v is not None else "N/A" for v in row]))
            cur.execute("SELECT coating_id FROM tbl_coating WHERE material_id = %s", (record_id,))
            chain = [f"Coating: {r[0]}" for r in cur.fetchall()]

    elif record_type == "coating":
        cur.execute("SELECT material_id, project, coating_date, made_by, coat_weight_gsm, porosity, notes FROM tbl_coating WHERE coating_id = %s", (record_id,))
        row = cur.fetchone()
        if row:
            columns = ["Material ID", "Project", "Coating Date", "Made By", "GSM", "Porosity", "Notes"]
            record = dict(zip(columns, [str(v) if v is not None else "N/A" for v in row]))
            cur.execute("SELECT slp_id FROM tbl_slp WHERE coating_id = %s", (record_id,))
            chain += [f"SLP: {r[0]}" for r in cur.fetchall()]
            cur.execute("SELECT coincell_id FROM tbl_coincell WHERE coating_id = %s", (record_id,))
            chain += [f"CoinCell: {r[0]}" for r in cur.fetchall()]
            cur.execute("SELECT mlp_id FROM tbl_mlp WHERE cat_coating_id = %s OR an_coating_id = %s", (record_id, record_id))
            chain += [f"MLP: {r[0]}" for r in cur.fetchall()]

    elif record_type == "slp":
        cur.execute("SELECT coating_id, project, date_made, made_by, electrolyte, formation_capacity, np_ratio, notes FROM tbl_slp WHERE slp_id = %s", (record_id,))
        row = cur.fetchone()
        if row:
            columns = ["Coating ID", "Project", "Date Made", "Made By", "Electrolyte", "Formation Capacity", "N/P Ratio", "Notes"]
            record = dict(zip(columns, [str(v) if v is not None else "N/A" for v in row]))
            chain = [f"Coating: {record['Coating ID']}"]

    elif record_type == "coincell":
        cur.execute("SELECT coating_id, project, date_made, made_by, electrolyte, formation_capacity, gsm, notes, cell_type FROM tbl_coincell WHERE coincell_id = %s", (record_id,))
        row = cur.fetchone()
        if row:
            columns = ["Coating ID", "Project", "Date Made", "Made By", "Electrolyte", "Formation Capacity", "GSM", "Notes", "Cell Type"]
            record = dict(zip(columns, [str(v) if v is not None else "N/A" for v in row]))
            chain = [f"Coating: {record['Coating ID']}"]

    elif record_type == "mlp":
        cur.execute("SELECT cat_coating_id, an_coating_id, project, date_made, cell_capacity, electrolyte, ac_area_ratio FROM tbl_mlp WHERE mlp_id = %s", (record_id,))
        row = cur.fetchone()
        if row:
            columns = ["Cathode Coating", "Anode Coating", "Project", "Date Made", "Cell Capacity", "Electrolyte", "A/C Area Ratio"]
            record = dict(zip(columns, [str(v) if v is not None else "N/A" for v in row]))
            chain = [f"Cathode: {record['Cathode Coating']}", f"Anode: {record['Anode Coating']}"]

    cur.close()
    conn.close()

    if not record:
        return JSONResponse({"error": "Record not found"}, status_code=404)

    return JSONResponse({"record_id": record_id, "record_type": record_type, "record": record, "chain": chain})

    # Generate the QR code for THIS card's own URL
    card_url = f"{BASE_URL}/card/{record_id}"
    qr_img = qrcode.make(card_url)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode()

    # Reuse the same lookup logic as /directory
    conn = get_connection()
    cur = conn.cursor()

    record = None
    chain = []

    if record_type == "coating":
        cur.execute(
            "SELECT material_id, project, coating_date, made_by, coat_weight_gsm, porosity, notes "
            "FROM tbl_coating WHERE coating_id = %s", (record_id,)
        )
        row = cur.fetchone()
        if row:
            columns = ["Material ID", "Project", "Coating Date", "Made By", "GSM", "Porosity", "Notes"]
            record = dict(zip(columns, row))
            cur.execute("SELECT slp_id FROM tbl_slp WHERE coating_id = %s", (record_id,))
            chain += [f"SLP: {r[0]}" for r in cur.fetchall()]
            cur.execute("SELECT coincell_id FROM tbl_coincell WHERE coating_id = %s", (record_id,))
            chain += [f"CoinCell: {r[0]}" for r in cur.fetchall()]
            cur.execute("SELECT mlp_id FROM tbl_mlp WHERE cat_coating_id = %s OR an_coating_id = %s", (record_id, record_id))
            chain += [f"MLP: {r[0]}" for r in cur.fetchall()]

    elif record_type == "material":
        cur.execute(
            "SELECT chemistry, supplier, date_received, quantity_kg, location, availability, notes "
            "FROM tbl_materials WHERE material_id = %s", (record_id,)
        )
    elif record_type == "slp":
        cur.execute(
            "SELECT coating_id, project, date_made, made_by, electrolyte, formation_capacity, np_ratio, notes "
            "FROM tbl_slp WHERE slp_id = %s", (record_id,)
        )
        row = cur.fetchone()
        if row:
            columns = ["Coating ID", "Project", "Date Made", "Made By", "Electrolyte", "Formation Capacity", "N/P Ratio", "Notes"]
            record = dict(zip(columns, row))
            chain.append(f"Coating: {record['Coating ID']}")

    elif record_type == "coincell":
        cur.execute(
            "SELECT coating_id, project, date_made, made_by, electrolyte, formation_capacity, cell_type, gsm, notes "
            "FROM tbl_coincell WHERE coincell_id = %s", (record_id,)
        )
        row = cur.fetchone()
        if row:
            columns = ["Coating ID", "Project", "Date Made", "Made By", "Electrolyte", "Formation Capacity", "Cell Type", "GSM", "Notes"]
            record = dict(zip(columns, row))
            chain.append(f"Coating: {record['Coating ID']}")

    elif record_type == "mlp":
        cur.execute(
            "SELECT cat_coating_id, an_coating_id, project, date_made, cell_capacity, electrolyte, ac_area_ratio "
            "FROM tbl_mlp WHERE mlp_id = %s", (record_id,)
        )
        row = cur.fetchone()
        if row:
            columns = ["Cathode Coating", "Anode Coating", "Project", "Date Made", "Cell Capacity", "Electrolyte", "A/C Area Ratio"]
            record = dict(zip(columns, row))
            chain.append(f"Cathode: {record['Cathode Coating']}")
            chain.append(f"Anode: {record['Anode Coating']}")
        
        row = cur.fetchone()
        if row:
            columns = ["Chemistry", "Supplier", "Date Received", "Quantity (kg)", "Location", "Availability", "Notes"]
            record = dict(zip(columns, row))
            cur.execute("SELECT coating_id FROM tbl_coating WHERE material_id = %s", (record_id,))
            chain += [f"Coating: {r[0]}" for r in cur.fetchall()]

    cur.close()
    conn.close()

    if not record:
        return HTMLResponse("Record not found.", status_code=404)

    return templates.TemplateResponse(
        "card.html",
        {"request": request, "record_id": record_id, "record_type": record_type,
         "record": record, "chain": chain, "qr_base64": qr_base64}
    )

@app.get("/api/chart/gsm-by-coating")
def chart_gsm():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT coating_id, coat_weight_gsm FROM tbl_coating WHERE coat_weight_gsm IS NOT NULL ORDER BY coating_id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return JSONResponse({"labels": [r[0] for r in rows], "values": [float(r[1]) for r in rows]})


@app.get("/api/chart/records-per-table")
def chart_records_per_table():
    conn = get_connection()
    cur = conn.cursor()
    counts = {}
    for label, table in [("Materials", "tbl_materials"), ("Coatings", "tbl_coating"),
                          ("SLP", "tbl_slp"), ("Coin Cells", "tbl_coincell"), ("MLP", "tbl_mlp")]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        counts[label] = cur.fetchone()[0]
    cur.close()
    conn.close()
    return JSONResponse({"labels": list(counts.keys()), "values": list(counts.values())})


@app.get("/api/graph")
def traceability_graph():
    conn = get_connection()
    cur = conn.cursor()

    nodes = []
    edges = []
    seen_projects = set()

    def add_project_node(project_name):
        if project_name and project_name not in seen_projects:
            nodes.append({"id": f"PROJECT-{project_name}", "label": project_name, "group": "project"})
            seen_projects.add(project_name)

    cur.execute("SELECT material_id, chemistry FROM tbl_materials")
    for mat_id, chem in cur.fetchall():
        nodes.append({"id": mat_id, "label": mat_id, "group": "material", "title": chem or ""})

    cur.execute("SELECT coating_id, material_id, project FROM tbl_coating")
    for coat_id, mat_id, project in cur.fetchall():
        nodes.append({"id": coat_id, "label": coat_id, "group": "coating"})
        edges.append({"from": mat_id, "to": coat_id})
        add_project_node(project)
        if project:
            edges.append({"from": coat_id, "to": f"PROJECT-{project}", "dashes": True})

    cur.execute("SELECT slp_id, coating_id, project FROM tbl_slp")
    for slp_id, coat_id, project in cur.fetchall():
        nodes.append({"id": slp_id, "label": slp_id, "group": "slp"})
        edges.append({"from": coat_id, "to": slp_id})
        add_project_node(project)
        if project:
            edges.append({"from": slp_id, "to": f"PROJECT-{project}", "dashes": True})

    cur.execute("SELECT coincell_id, coating_id, project FROM tbl_coincell")
    for cc_id, coat_id, project in cur.fetchall():
        nodes.append({"id": cc_id, "label": cc_id, "group": "coincell"})
        edges.append({"from": coat_id, "to": cc_id})
        add_project_node(project)
        if project:
            edges.append({"from": cc_id, "to": f"PROJECT-{project}", "dashes": True})

    cur.execute("SELECT mlp_id, cat_coating_id, an_coating_id, project FROM tbl_mlp")
    for mlp_id, cat_id, an_id, project in cur.fetchall():
        nodes.append({"id": mlp_id, "label": mlp_id, "group": "mlp"})
        edges.append({"from": cat_id, "to": mlp_id})
        edges.append({"from": an_id, "to": mlp_id})
        add_project_node(project)
        if project:
            edges.append({"from": mlp_id, "to": f"PROJECT-{project}", "dashes": True})

    cur.close()
    conn.close()
    return JSONResponse({"nodes": nodes, "edges": edges})

@app.get("/graph", response_class=HTMLResponse)
def graph_page(request: Request):
    return templates.TemplateResponse("graph.html", {"request": request})

@app.get("/api/chart/coatings-over-time")
def chart_coatings_over_time():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT coating_date, COUNT(*) 
        FROM tbl_coating 
        WHERE coating_date IS NOT NULL 
        GROUP BY coating_date 
        ORDER BY coating_date
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return JSONResponse({"labels": [str(r[0]) for r in rows], "values": [r[1] for r in rows]})

@app.get("/HAZbot", response_class=HTMLResponse)
def HAZbot_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse("HAZbot.html", {"request": request})


@app.post("/api/HAZbot/ask")
def HAZbot_ask(request: Request, question: str = Form(...)):
    raw = ask_ai_for_sql(question)

    if raw.startswith("ERROR"):
        return JSONResponse({"error": raw}, status_code=502)

    sql_part, insight_part = "", ""
    for line in raw.splitlines():
        if line.strip().upper().startswith("SQL:"):
            sql_part = line.split(":", 1)[1].strip()
        elif line.strip().upper().startswith("INSIGHT:"):
            insight_part = line.split(":", 1)[1].strip()

    if not sql_part:
        return JSONResponse({"error": f"Couldn't parse AI response: {raw}"}, status_code=502)

    if not sql_part.upper().startswith("SELECT"):
        return JSONResponse({"error": "Generated query was not a SELECT statement — blocked for safety."}, status_code=400)

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql_part)
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        results = [dict(zip(columns, [str(v) if v is not None else None for v in row])) for row in rows]
    except Exception as e:
        cur.close()
        conn.close()
        return JSONResponse({"error": f"SQL execution failed: {str(e)}", "sql": sql_part}, status_code=400)

    cur.close()
    conn.close()

    return JSONResponse({"sql": sql_part, "insight": insight_part, "columns": columns, "results": results})
