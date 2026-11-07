"""Home page."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from core.auth import require_login
from core.templates import templates
from services.account import has_users

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Home page, or the setup page if there are no users yet."""
    if not has_users():
        return templates.TemplateResponse(request, "unsetup.html")
    redirect = require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "home.html")
