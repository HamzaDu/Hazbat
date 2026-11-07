"""API keys for the logged-in user: list them, create one (shown once) and revoke one. Template: api_keys.html."""

from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from core.auth import require_session
from core.templates import templates
from services.api import create_api_key, list_api_keys, revoke_api_key

router = APIRouter()


@router.get("/api-keys", response_class=HTMLResponse)
def api_keys_page(request: Request):
    """The logged-in user's API keys."""
    redirect = require_session(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "api_keys.html", {"keys": list_api_keys(request.session["user_id"])})


@router.post("/api-keys/new", response_class=HTMLResponse)
def submit_new_api_key(request: Request, name: str = Form(...), expires_at: str = Form(None)):
    """Create an API key, with an optional expiry date, and show it once."""
    redirect = require_session(request)
    if redirect:
        return redirect
    user_id = request.session["user_id"]

    name = name.strip()
    error = None
    success = None
    new_key = None
    expires_on = None

    if not name:
        error = "Name is required."
    elif expires_at and expires_at.strip():
        try:
            expires_on = datetime.strptime(expires_at.strip(), "%Y-%m-%d").date()
        except ValueError:
            error = "Expiry date must be YYYY-MM-DD."
        else:
            if expires_on < datetime.now().date():
                error = "Expiry date must not be in the past."

    if not error:
        new_key = create_api_key(user_id, name, expires_on)
        success = f"Key '{name}' created."

    return templates.TemplateResponse(request, "api_keys.html", {"keys": list_api_keys(user_id), "new_key": new_key, "error": error, "success": success})


@router.post("/api-keys/{key_id}/revoke", response_class=HTMLResponse)
def submit_revoke_api_key(request: Request, key_id: int):
    """Revoke one of the logged-in user's API keys."""
    redirect = require_session(request)
    if redirect:
        return redirect
    user_id = request.session["user_id"]

    if revoke_api_key(user_id, key_id):
        error, success = None, "Key revoked."
    else:
        error, success = "Key not found or already revoked.", None

    return templates.TemplateResponse(request, "api_keys.html", {"keys": list_api_keys(user_id), "error": error, "success": success})
