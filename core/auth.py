"""Login and project-permission checks used by the routers.

Pages that need a login start with:
    redirect = require_login(request)
    if redirect:
        return redirect
"""

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from core.config import SESSION_SECRET
from services.account import get_login_details, get_session_state
from services.api import get_api_key_user
from services.two_factor import get_trust_info

# One signed cookie per user records that this browser passed their second-factor check
signer = URLSafeTimedSerializer(SESSION_SECRET, salt="hazbat-2fa-device")


def trust_cookie_name(user_id):
    """Name of the cookie for one user, so people who share a browser do not overwrite each other's."""
    return f"hazbat_2fa_{user_id}"


def current_user(request: Request):
    """The logged-in user's details: from the session, or from the API key require_login accepted."""
    if request.session.get("user_id"):
        return request.session
    return getattr(request.state, "user", {})


def refresh_session(request: Request):
    """Re-reads the logged-in user from the database, so a lock, a deletion or a change of role or projects
    takes effect on the next request. Ends the session and returns False if the user is gone or locked."""
    state = get_session_state(request.session["user_id"])
    if state is None:
        request.session.clear()
        return False
    request.session["full_name"] = state[0]
    request.session["is_admin"] = state[1]
    request.session["projects"] = state[2]
    return True


def require_login(request: Request):
    """Send the user to /login if they are not logged in (returns None when they are).
    An API key in an Authorization: Bearer header also counts; an invalid one gets a 401."""
    if request.session.get("user_id"):
        if refresh_session(request):
            return None
        return RedirectResponse(url="/login", status_code=303)
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        user = get_api_key_user(auth[7:].strip())
        if not user:
            return JSONResponse({"error": "Invalid API key"}, status_code=401)
        request.state.user = user
        return None
    return RedirectResponse(url="/login", status_code=303)


def require_session(request: Request):
    """Like require_login, but only a browser login session counts, not an API key."""
    if not request.session.get("user_id") or not refresh_session(request):
        return RedirectResponse(url="/login", status_code=303)
    return None


def device_trusted(request: Request, user_id):
    """True if this browser holds a valid cookie from an earlier second-factor check for this user:
    correctly signed, not older than the user's interval, and issued for their current authenticator.
    An interval of zero means the second factor is asked for at every login."""
    info = get_trust_info(user_id)
    if info is None or info[1] <= 0:
        return False
    cookie = request.cookies.get(trust_cookie_name(user_id))
    if not cookie:
        return False
    try:
        data = signer.loads(cookie, max_age=info[1])
    except BadSignature:  # also covers an expired signature
        return False
    return data == {"user_id": user_id, "twofa_id": info[0]}


def trust_device(response, user_id):
    """Puts the device cookie on a response after a successful second-factor check (nothing if the interval is zero)."""
    info = get_trust_info(user_id)
    if info is None or info[1] <= 0:
        return
    value = signer.dumps({"user_id": user_id, "twofa_id": info[0]})
    response.set_cookie(trust_cookie_name(user_id), value, max_age=info[1], httponly=True, samesite="lax")


def complete_login(request: Request, user_id):
    """Turns a pending login into a full session once the second factor has passed."""
    full_name, is_admin, projects = get_login_details(user_id)
    request.session.clear()
    request.session["user_id"] = user_id
    request.session["full_name"] = full_name
    request.session["is_admin"] = is_admin
    request.session["projects"] = projects


def get_allowed_projects(request: Request):
    """Returns None if the user can see everything (admin), or a list of
    allowed project names to filter by."""
    user = current_user(request)
    if user.get("is_admin"):
        return None
    return user.get("projects", [])
