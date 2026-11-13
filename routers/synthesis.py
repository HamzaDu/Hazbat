"""Synthesis steps of a material: the page, and the JSON it uses.

GET    /materials/{id}/synthesis       the page (synthesis.html, js/synthesis.js)
GET    /api/materials/{id}/synthesis   every step, in order
POST   /api/materials/{id}/synthesis   add a step (JSON body; no step_no = last + 1)
PUT    /api/synthesis/{step_id}        replace a step's values
DELETE /api/synthesis/{step_id}        remove a step

Checks and database work are in services/synthesis.py. Only GET /api/... is an MCP tool.
"""

from typing import Annotated

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core.auth import current_user, get_allowed_projects, require_login
from core.templates import templates
from services.coa import material_summaries
from services.forms import record_exists
from services.records import detect_record_type, record_visible
from services.synthesis import (
    STEP_TYPES,
    SynthesisError,
    add_step,
    delete_step,
    get_step,
    list_steps,
    update_step,
)

router = APIRouter()


def material_found(request: Request, material_id: str) -> bool:
    """True if the material exists and this user may see it."""
    if not record_visible(material_id, get_allowed_projects(request)):
        return False
    return record_exists("tbl_materials", "material_id", material_id)


def step_found(request: Request, step_id: int):
    """The step if it exists and this user may see its material, else None."""
    step = get_step(step_id)
    if not step:
        return None
    if not record_visible(step["material_id"], get_allowed_projects(request)):
        return None
    return step


def not_found(what: str):
    return JSONResponse({"error": f"{what} not found"}, status_code=404)


@router.get("/materials/{material_id}/synthesis", response_class=HTMLResponse)
def synthesis_page(request: Request, material_id: str):
    """A material's synthesis route: the steps in order, and a form to add or
    edit one. The steps are loaded by static/js/synthesis.js.
    """
    redirect = require_login(request)
    if redirect:
        return redirect
    if detect_record_type(material_id) != "material":
        return HTMLResponse("Material not found.", status_code=404)
    if not material_found(request, material_id):
        return HTMLResponse("Material not found.", status_code=404)
    return templates.TemplateResponse(
        request,
        "synthesis.html",
        {
            "material": material_summaries([material_id])[0],
            "step_types": STEP_TYPES,
            "full_name": current_user(request).get("full_name"),
        },
    )


@router.get("/api/materials/{material_id}/synthesis")
def material_synthesis(request: Request, material_id: str):
    """Every synthesis step of a material, in order."""
    redirect = require_login(request)
    if redirect:
        return redirect
    if not material_found(request, material_id):
        return not_found("Material")
    return {
        "material_id": material_id,
        "step_types": list(STEP_TYPES),
        "steps": list_steps(material_id),
    }


@router.post("/api/materials/{material_id}/synthesis")
def add_synthesis_step(
    request: Request, material_id: str, values: Annotated[dict, Body()]
):
    """Add a step. Replies with the new step."""
    redirect = require_login(request)
    if redirect:
        return redirect
    if not material_found(request, material_id):
        return not_found("Material")
    try:
        step = add_step(material_id, values)
    except SynthesisError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"step": step}, status_code=201)


@router.put("/api/synthesis/{step_id}")
def edit_synthesis_step(
    request: Request, step_id: int, values: Annotated[dict, Body()]
):
    """Replace a step's values. Replies with the step as saved."""
    redirect = require_login(request)
    if redirect:
        return redirect
    if not step_found(request, step_id):
        return not_found("Step")
    try:
        step = update_step(step_id, values)
    except SynthesisError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not step:  # deleted in the meantime
        return not_found("Step")
    return {"step": step}


@router.delete("/api/synthesis/{step_id}")
def remove_synthesis_step(request: Request, step_id: int):
    """Remove a step."""
    redirect = require_login(request)
    if redirect:
        return redirect
    if not step_found(request, step_id) or not delete_step(step_id):
        return not_found("Step")
    return {"deleted": step_id}
