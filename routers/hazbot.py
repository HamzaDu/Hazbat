"""HAZbot: ask a question in plain English and get a SQL query and its results.

HAZbot.py sends the question to the AI model; only SELECT queries are run.
Template: HAZbot.html.
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from HAZbot import ask_ai_for_sql
from core.auth import require_login
from core.db import get_connection
from core.templates import templates

router = APIRouter()


@router.get("/HAZbot", response_class=HTMLResponse)
def HAZbot_page(request: Request):
    """HAZbot page."""
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "HAZbot.html")


@router.post("/api/HAZbot/ask")
def HAZbot_ask(request: Request, question: str = Form(...)):
    """Turn a question into SQL with the AI model, run it if it is a SELECT, and return the results."""
    redirect = require_login(request)
    if redirect:
        return redirect
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

    conn = get_connection(read_only=True)
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
