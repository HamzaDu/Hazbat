"""Project management (admins only): list the projects, create one, and switch one on or off.

An inactive project is left out of the lists offered when users and records are created. Existing records and users
keep it. Templates: manage_projects.html, manage_project.html, create_project.html.

None of these endpoints may be exposed through the MCP interface (routers/mcp_server.py).
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from core.templates import templates
from routers.users import require_admin
from services.projects import create_project, get_project, list_projects, set_project_active

router = APIRouter()


def projects_page(request: Request, error=None, success=None):
    """The list of projects."""
    return templates.TemplateResponse(request, "manage_projects.html", {"projects": list_projects(),
                                                                        "error": error, "success": success})


def project_page(request: Request, project_name: str, error=None, success=None):
    """The page for one project, or a 404 page if there is no such project."""
    project = get_project(project_name)
    if project is None:
        return HTMLResponse("That project does not exist.", status_code=404)
    return templates.TemplateResponse(request, "manage_project.html", {"project": project, "error": error,
                                                                       "success": success})


@router.get("/admin/projects", response_class=HTMLResponse)
def projects_list(request: Request):
    """All projects, with how many records and users each has."""
    denied = require_admin(request)
    if denied:
        return denied
    return projects_page(request)


# This route must come before the one for a single project, or "new" would be taken as a project name
@router.get("/admin/projects/new", response_class=HTMLResponse)
def new_project_form(request: Request):
    """The form for a new project."""
    denied = require_admin(request)
    if denied:
        return denied
    return templates.TemplateResponse(request, "create_project.html", {"name": ""})


@router.post("/admin/projects/new", response_class=HTMLResponse)
def submit_new_project(request: Request, name: str = Form(...)):
    """Create a project."""
    denied = require_admin(request)
    if denied:
        return denied
    name = name.strip()
    error = create_project(name)
    if error:
        return templates.TemplateResponse(request, "create_project.html", {"name": name, "error": error})
    return projects_page(request, success=f"Project '{name}' created.")


@router.get("/admin/projects/{project_name}", response_class=HTMLResponse)
def project_detail(request: Request, project_name: str):
    """One project, with the button that switches it on or off."""
    denied = require_admin(request)
    if denied:
        return denied
    return project_page(request, project_name)


@router.post("/admin/projects/{project_name}/active", response_class=HTMLResponse)
def submit_project_active(request: Request, project_name: str, active: str = Form(...)):
    """Switch a project on ("true") or off ("false")."""
    denied = require_admin(request)
    if denied:
        return denied
    if not set_project_active(project_name, active == "true"):
        return HTMLResponse("That project does not exist.", status_code=404)
    if active == "true":
        return project_page(request, project_name, success="Project activated.")
    return project_page(request, project_name, success="Project deactivated.")
