import os
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

SCHEMA_DESCRIPTION = """
tbl_materials(material_id, chemistry, supplier, date_received, quantity_kg, location, availability)
tbl_coating(coating_id, material_id, project, coating_date, made_by, coat_weight_gsm, porosity)
tbl_slp(slp_id, coating_id, project, date_made, made_by, electrolyte, formation_capacity)
tbl_coincell(coincell_id, coating_id, project, date_made, made_by, electrolyte, formation_capacity)
tbl_mlp(mlp_id, cat_coating_id, an_coating_id, project, date_made, cell_capacity)
"""


def ask_ai_for_sql(question: str) -> str:
    prompt = (
        "You are a SQL generator for a PostgreSQL database. Schema:\n"
        f"{SCHEMA_DESCRIPTION}\n"
        "Given the question below, respond in EXACTLY this format, nothing else:\n"
        "SQL: <one PostgreSQL SELECT query, no semicolon>\n"
        "INSIGHT: <one plain-English sentence on what this query reveals>\n"
        f"Question: {question}"
    )

    response = requests.post(
        GEMINI_URL,
        params={"key": GEMINI_API_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=15
    )

    if response.status_code != 200:
        return f"ERROR: {response.status_code} - {response.text}"

    data = response.json()
    try:
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return "ERROR: Unexpected response shape from Gemini"

    return raw_text