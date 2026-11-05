"""User management (admins only): list users, lock or unlock them, delete them, set their password
and reset their two-factor authentication.

Template: users.html. Tables: tbl_users and the tables that hang off it.

None of these endpoints may be exposed through the MCP interface (routers/mcp_server.py).
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from core.auth import require_session
from core.templates import templates
from services.account import set_user_password
from services.two_factor import reset_2fa
from services.users import delete_user, get_user_for_edit, list_users, set_user_locked, update_user

# Do not add any route in this file to the MCP tools: they change or delete accounts, and they are admin-only on purpose
router = APIRouter()


def require_admin(request: Request):
    """Redirects to /login if there is no browser session and returns a 403 page if the user is not an admin.
    Returns None for an admin. API keys are not accepted here."""
    redirect = require_session(request)
    if redirect:
        return redirect
    if not request.session.get("is_admin"):
        return HTMLResponse("Admins only.", status_code=403)
    return None


def users_page(request: Request, error=None, success=None):
    """The user management page."""
    return templates.TemplateResponse(request, "users.html", {"users": list_users(), "own_id": request.session["user_id"],
                                                              "error": error, "success": success})


def edit_page(request: Request, user_id: int, error=None, success=None, open_section=None):
    """The edit page for one user. open_section names the drawer to show open ('password' or 'reset-2fa')."""
    user = get_user_for_edit(user_id)
    if user is None:
        return HTMLResponse("That user does not exist.", status_code=404)
    return templates.TemplateResponse(request, "edit_user.html", {"user": user, "own_id": request.session["user_id"],
                                                                  "error": error, "success": success,
                                                                  "open_section": open_section})


@router.get("/admin/users", response_class=HTMLResponse)
def users_list(request: Request):
    """All users, with the actions an admin can take on each."""
    denied = require_admin(request)
    if denied:
        return denied
    return users_page(request)


@router.post("/admin/users/{user_id}/lock", response_class=HTMLResponse)
def lock_user(request: Request, user_id: int):
    """Lock a user (not yourself): they cannot log in and their sessions and API keys stop working."""
    denied = require_admin(request)
    if denied:
        return denied
    if user_id == request.session["user_id"]:
        return users_page(request, error="You cannot lock your own account.")
    set_user_locked(user_id, True)
    return users_page(request, success="User locked.")


@router.post("/admin/users/{user_id}/unlock", response_class=HTMLResponse)
def unlock_user(request: Request, user_id: int):
    """Unlock a user."""
    denied = require_admin(request)
    if denied:
        return denied
    set_user_locked(user_id, False)
    return users_page(request, success="User unlocked.")


@router.post("/admin/users/{user_id}/delete", response_class=HTMLResponse)
def remove_user(request: Request, user_id: int):
    """Delete a user (not yourself), together with their API keys and two-factor data."""
    denied = require_admin(request)
    if denied:
        return denied
    if user_id == request.session["user_id"]:
        return users_page(request, error="You cannot delete your own account.")
    if not delete_user(user_id):
        return users_page(request, error="That user does not exist.")
    return users_page(request, success="User deleted.")


@router.post("/admin/users/{user_id}/password", response_class=HTMLResponse)
def set_password(request: Request, user_id: int, new_password: str = Form(...)):
    """Set a user's password."""
    denied = require_admin(request)
    if denied:
        return denied
    if not new_password:
        return edit_page(request, user_id, error="The new password must not be empty.", open_section="password")
    if len(new_password.encode()) > 72:
        return edit_page(request, user_id, error="The new password must be at most 72 bytes (bcrypt limit).",
                         open_section="password")
    set_user_password(user_id, new_password)
    return edit_page(request, user_id, success="Password set.")


@router.post("/admin/users/{user_id}/reset-2fa", response_class=HTMLResponse)
def reset_user_two_factor(request: Request, user_id: int):
    """Remove a user's authenticator and recovery codes; they set up a new one at their next login."""
    denied = require_admin(request)
    if denied:
        return denied
    reset_2fa(user_id)
    return edit_page(request, user_id, success="Two-factor authentication reset.")


@router.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
def edit_user_page(request: Request, user_id: int):
    """Edit one user: full name, admin access and projects, with their password and two-factor reset."""
    denied = require_admin(request)
    if denied:
        return denied
    return edit_page(request, user_id)


@router.post("/admin/users/{user_id}/edit", response_class=HTMLResponse)
def save_user(request: Request, user_id: int, full_name: str = Form(...), is_admin: str = Form(None),
              projects: list = Form(default=[])):
    """Save a user's full name, admin access and projects. You cannot remove your own admin access."""
    denied = require_admin(request)
    if denied:
        return denied
    full_name = full_name.strip()
    if not full_name:
        return edit_page(request, user_id, error="The full name must not be empty.")
    if user_id == request.session["user_id"] and is_admin != "on":
        return edit_page(request, user_id, error="You cannot remove your own admin access.")
    try:
        update_user(user_id, full_name, is_admin == "on", projects)
    except Exception as e:
        return edit_page(request, user_id, error=str(e))
    return edit_page(request, user_id, success="User saved.")
