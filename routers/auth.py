"""Login, logout and adding users (admin only).

Logging in checks the password, then sends the user to set up or enter a second factor (main.py).
Once that passes, user_id, full_name, is_admin and the user's projects are stored in the
session cookie; core/auth.py reads them back.
Tables: tbl_users, tbl_user_projects, tbl_projects.
"""

from datetime import timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core.auth import complete_login, current_user, device_trusted, require_login, require_session
from core.config import DISABLE_2FA, MAX_2FA_INTERVAL_HOURS
from core.db import get_admin_connection, get_connection
from core.templates import templates
from services.account import (check_password, get_user_info, has_users, hash_password, set_user_full_name,
                              set_user_password, verify_user_password)
from services.two_factor import has_confirmed_2fa, reset_2fa, set_2fa_interval

router = APIRouter()


# --- Login / logout ----------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    """Show the login page, or send the visitor to the setup page (on /) if there are no users yet."""
    if not has_users():
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html")


@router.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    """Check username and password, then send the user to set up or enter their second factor."""
    conn = get_admin_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, password_hash, locked FROM tbl_users WHERE username = %s", (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()

    too_long = len(password.encode()) > 72  # longer than bcrypt can hold, so it cannot be a stored password
    if not user or too_long or not check_password(password, user[1]):
        return templates.TemplateResponse(request, "login.html", {"error": "Invalid username or password."})
    if user[2]:
        return templates.TemplateResponse(request, "login.html", {"error": "This account is locked. Contact an administrator."})

    user_id = user[0]
    if DISABLE_2FA:
        complete_login(request, user_id)
        return RedirectResponse(url="/", status_code=303)
    request.session["pending_user_id"] = user_id
    request.session["pending_username"] = username

    if not has_confirmed_2fa(user_id):
        return RedirectResponse(url="/2fa", status_code=303)
    if device_trusted(request, user_id):
        complete_login(request, user_id)
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url="/2fa/verify", status_code=303)


@router.get("/logout")
def logout(request: Request):
    """Clear the session and go back to the home page."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


# --- Session check -----------------------------------------------------------

@router.get("/debug/session")
def debug_session(request: Request):
    """Show what is stored in the current session (for checking logins and project access)."""
    redirect = require_login(request)
    if redirect:
        return redirect
    return {
        "user_id": request.session.get("user_id"),
        "full_name": request.session.get("full_name"),
        "is_admin": request.session.get("is_admin"),
        "projects": request.session.get("projects"),
    }


# --- Users (admin only) ------------------------------------------------------

@router.get("/admin/users/new", response_class=HTMLResponse)
def new_user_form(request: Request):
    """Form for adding a user (admins only)."""
    redirect = require_login(request)
    if redirect:
        return redirect
    if not current_user(request).get("is_admin"):
        return HTMLResponse("Admins only.", status_code=403)

    conn = get_connection(read_only=True)
    cur = conn.cursor()
    cur.execute("SELECT project_name FROM tbl_projects WHERE active = true ORDER BY project_name")
    projects = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    return templates.TemplateResponse(request, "new_user.html", {"projects": projects})


@router.post("/admin/users/new", response_class=HTMLResponse)
def submit_new_user(request: Request, username: str = Form(...), password: str = Form(...),
                     full_name: str = Form(...), is_admin: str = Form(None),
                     projects: list = Form(default=[])):
    """Create a user and give them access to the chosen projects (admins only)."""
    redirect = require_login(request)
    if redirect:
        return redirect
    if not current_user(request).get("is_admin"):
        return HTMLResponse("Admins only.", status_code=403)

    username = username.strip()
    full_name = full_name.strip()
    error = None
    success = None

    conn = get_admin_connection()
    cur = conn.cursor()
    cur.execute("SELECT project_name FROM tbl_projects WHERE active = true ORDER BY project_name")
    all_projects = [row[0] for row in cur.fetchall()]

    if not username or not password or not full_name:
        error = "Username, password, and full name are all required."
    elif len(password.encode()) > 72:
        error = "The password must be at most 72 bytes (bcrypt limit)."
    else:
        password_hash = hash_password(password)
        try:
            cur.execute(
                "INSERT INTO tbl_users (username, password_hash, full_name, is_admin) VALUES (%s, %s, %s, %s) RETURNING user_id",
                (username, password_hash, full_name, is_admin == "on")
            )
            new_user_id = cur.fetchone()[0]

            for project in projects:
                cur.execute(
                    "INSERT INTO tbl_user_projects (user_id, project_name) VALUES (%s, %s)",
                    (new_user_id, project)
                )
            conn.commit()
            success = f"User '{username}' created with access to: {', '.join(projects) if projects else 'no projects'}."
        except Exception as e:
            conn.rollback()
            error = str(e)

    cur.close()
    conn.close()
    return templates.TemplateResponse(request, "new_user.html", {"projects": all_projects, "error": error, "success": success})


# --- My account --------------------------------------------------------------

def account_page(request: Request, error=None, success=None, open_section=None):
    """The My Account page for the logged-in user. open_section names the drawer to show open ('name', 'password', '2fa-interval' or 'reset-2fa')."""
    info = get_user_info(request.session["user_id"])
    return templates.TemplateResponse(request, "user_info.html", {"info": info, "error": error, "success": success,
                                                                  "open_section": open_section,
                                                                  "max_hours": MAX_2FA_INTERVAL_HOURS})


@router.get("/user-info", response_class=HTMLResponse)
def user_info_page(request: Request):
    """The user's details, with forms to change their password and reset their two-factor authentication."""
    redirect = require_session(request)
    if redirect:
        return redirect
    return account_page(request)


@router.post("/user-info/name", response_class=HTMLResponse)
def change_name(request: Request, full_name: str = Form(...)):
    """Change the logged-in user's own full name. Nothing else about the account can be changed here."""
    redirect = require_session(request)
    if redirect:
        return redirect
    full_name = full_name.strip()
    if not full_name:
        return account_page(request, error="The full name must not be empty.", open_section="name")

    set_user_full_name(request.session["user_id"], full_name)
    request.session["full_name"] = full_name
    return account_page(request, success="Full name changed.")


@router.post("/user-info/password", response_class=HTMLResponse)
def change_password(request: Request, current_password: str = Form(...), new_password: str = Form(...),
                    confirm_password: str = Form(...)):
    """Change the logged-in user's password; the current one must be given."""
    redirect = require_session(request)
    if redirect:
        return redirect
    user_id = request.session["user_id"]

    if not verify_user_password(user_id, current_password):
        return account_page(request, error="Current password is incorrect.", open_section="password")
    if not new_password:
        return account_page(request, error="The new password must not be empty.", open_section="password")
    if new_password != confirm_password:
        return account_page(request, error="The new passwords do not match.", open_section="password")
    if len(new_password.encode()) > 72:
        return account_page(request, error="The new password must be at most 72 bytes (bcrypt limit).",
                            open_section="password")

    set_user_password(user_id, new_password)
    return account_page(request, success="Password changed.")


@router.post("/user-info/2fa-interval", response_class=HTMLResponse)
def change_2fa_interval(request: Request, hours: int = Form(...)):
    """Set how many hours the logged-in user's browser is trusted after a second-factor check (0 = every login).
    The longest allowed is max_2fa_interval_hours in the config file."""
    redirect = require_session(request)
    if redirect:
        return redirect
    if hours < 0 or hours > MAX_2FA_INTERVAL_HOURS:
        return account_page(request, error=f"The time must be between 0 and {MAX_2FA_INTERVAL_HOURS} hours.",
                            open_section="2fa-interval")

    set_2fa_interval(request.session["user_id"], timedelta(hours=hours))
    return account_page(request, success="Time between two-factor checks saved.")


@router.post("/user-info/reset-2fa", response_class=HTMLResponse)
def reset_two_factor(request: Request, current_password: str = Form(...)):
    """Remove the logged-in user's authenticator and recovery codes; the current password must be given."""
    redirect = require_session(request)
    if redirect:
        return redirect
    user_id = request.session["user_id"]

    if not verify_user_password(user_id, current_password):
        return account_page(request, error="Current password is incorrect.", open_section="reset-2fa")

    reset_2fa(user_id)
    return account_page(request, success="Two-factor authentication reset. You will set up a new authenticator the next time you log in.")
