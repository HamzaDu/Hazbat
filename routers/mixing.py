"""Mixing page: upload a mixer log and look at it (templates/mixing.html).

GET  /mixing                 the page (inputs on the left, charts in the middle)
POST /mixing                 save a log, its ingredients and the coating it fed
GET  /api/mixing             the runs this user may see
GET  /api/mixing/model       train the power model on those runs
GET  /api/mixing/{id}        one run: summary, stages, ingredients, links, the log

Reading the log and saving it are in services/mixing.py; the model is in
services/mixing_model.py. The charts are drawn by static/js/mixing.js.
"""

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from core.auth import current_user, get_allowed_projects, require_login
from core.templates import templates
from services.forms import load_form_options
from services.mixing import (
    ROLES,
    MixingError,
    clean_ingredients,
    get_run,
    list_runs,
    load_logs,
    next_mixing_id,
    save_mixing_run,
)
from services.mixing_model import ModelError, train_and_score

router = APIRouter()


def page_context(request: Request, **extra):
    """Everything mixing.html needs: dropdown lists, defaults and the run list."""
    options = load_form_options()
    allowed = get_allowed_projects(request)
    if allowed is not None:
        options["projects"] = [p for p in options["projects"] if p in allowed]
    return {
        **options,
        "roles": ROLES,
        "runs": list_runs(allowed),
        "default_id": next_mixing_id(),
        "full_name": current_user(request).get("full_name") or "",
        "selected": request.query_params.get("run"),
        "saved": request.query_params.get("saved"),
        "form": {},
        "error": None,
        **extra,
    }


@router.get("/mixing", response_class=HTMLResponse)
def mixing_page(request: Request):
    """The mixing page: add a run, pick one, see its charts."""
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "mixing.html", page_context(request))


@router.post("/mixing", response_class=HTMLResponse)
async def submit_mixing(
    request: Request,
    mixing_id: Annotated[str, Form()],
    project: Annotated[str, Form()],
    made_by: Annotated[str, Form()] = "",
    coating_id: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    ingredient_material: Annotated[list[str] | None, Form()] = None,
    ingredient_role: Annotated[list[str] | None, Form()] = None,
    ingredient_mass: Annotated[list[str] | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
):
    """Check the form and save the run. On success, go to its page."""
    redirect = require_login(request)
    if redirect:
        return redirect

    form = {
        "mixing_id": mixing_id.strip(),
        "project": project.strip(),
        "made_by": made_by.strip(),
        "coating_id": coating_id.strip(),
        "notes": notes.strip(),
    }
    rows = list(
        zip(
            ingredient_material or [],
            ingredient_role or [],
            ingredient_mass or [],
            strict=False,
        )
    )
    form["ingredients"] = [
        {"material": m, "role": r, "mass": g} for m, r, g in rows if m or g
    ]

    def fail(message):
        return templates.TemplateResponse(
            request,
            "mixing.html",
            page_context(request, error=message, form=form),
            status_code=400,
        )

    allowed = get_allowed_projects(request)
    if not form["project"] or (allowed is not None and form["project"] not in allowed):
        return fail("Choose one of your projects.")
    if file is None or not file.filename:
        return fail("Choose the mixer log (.xlsx) to upload.")
    if not file.filename.lower().endswith(".xlsx"):
        return fail("The mixer log must be an .xlsx file.")
    ingredients, error = clean_ingredients(rows)
    if error:
        return fail(error)

    try:
        save_mixing_run(
            form["mixing_id"],
            form["project"],
            form["made_by"] or None,
            file.filename,
            await file.read(),
            ingredients,
            form["coating_id"] or None,
            form["notes"] or None,
        )
    except MixingError as e:
        return fail(str(e))
    return RedirectResponse(f"/mixing?run={form['mixing_id']}&saved=1", status_code=303)


@router.get("/api/mixing")
def api_mixing_runs(request: Request):
    """The runs this user may see."""
    redirect = require_login(request)
    if redirect:
        return redirect
    return {"runs": list_runs(get_allowed_projects(request))}


@router.get("/api/mixing/model")
def api_mixing_model(request: Request):
    """Train the power model on every run this user may see, and score it."""
    redirect = require_login(request)
    if redirect:
        return redirect
    try:
        return train_and_score(load_logs(get_allowed_projects(request)))
    except ModelError as e:
        return JSONResponse({"error": str(e)}, status_code=422)


@router.get("/api/mixing/{mixing_id}")
def api_mixing_run(request: Request, mixing_id: str):
    """One run in full."""
    redirect = require_login(request)
    if redirect:
        return redirect
    run = get_run(mixing_id, get_allowed_projects(request))
    if not run:
        return JSONResponse({"error": "Mixing run not found"}, status_code=404)
    return run
