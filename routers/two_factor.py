"""The second step of login: setting up an authenticator and entering a code.

A user who has passed the password check (routers/auth.py) has pending_user_id and pending_username in the session.
/2fa sets up an authenticator for a user who has none, and /2fa/verify checks a code or a recovery code for one who has.
A correct code finishes the login. Templates: scanTOTP.html, enterTOTP.html.
"""

import base64

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core.auth import complete_login, trust_device
from core.templates import templates
from services.cards import make_qr_png
from services.two_factor import (confirm_totp, get_pending_totp, has_confirmed_2fa, start_totp_enrolment,
                                 verify_second_factor)

router = APIRouter()


def enrolment_page(request: Request, secret, uri, codes, error=None):
    """The page that shows the QR code, secret and recovery codes for a new authenticator."""
    qr_base64 = base64.b64encode(make_qr_png(uri)).decode()
    return templates.TemplateResponse(request, "scanTOTP.html", {"qr_base64": qr_base64, "secret": secret,
                                                                 "uri": uri, "recovery_codes": codes, "error": error})


@router.get("/2fa", response_class=HTMLResponse)
def two_factor_page(request: Request):
    """Set up an authenticator: for a user who has passed the password check and has none yet."""
    user_id = request.session.get("pending_user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    if has_confirmed_2fa(user_id):
        return RedirectResponse(url="/2fa/verify", status_code=303)
    secret, uri, codes = start_totp_enrolment(user_id, request.session["pending_username"])
    request.session["pending_codes"] = codes
    return enrolment_page(request, secret, uri, codes)


@router.post("/2fa/confirm", response_class=HTMLResponse)
def two_factor_confirm(request: Request, code: str = Form(...)):
    """Check the first code from the new authenticator, then finish the login."""
    user_id = request.session.get("pending_user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    if confirm_totp(user_id, code.strip()):
        complete_login(request, user_id)
        response = RedirectResponse(url="/", status_code=303)
        trust_device(response, user_id)
        return response
    pending = get_pending_totp(user_id, request.session["pending_username"])
    if not pending:
        return RedirectResponse(url="/2fa", status_code=303)
    secret, uri = pending
    return enrolment_page(request, secret, uri, request.session.get("pending_codes", []), "That code was not valid.")


@router.get("/2fa/verify", response_class=HTMLResponse)
def two_factor_verify_page(request: Request):
    """The page where a user with an authenticator enters a code."""
    if not request.session.get("pending_user_id"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "enterTOTP.html")


@router.post("/2fa/verify", response_class=HTMLResponse)
def two_factor_verify(request: Request, code: str = Form(...)):
    """Check a code or a recovery code, then finish the login."""
    user_id = request.session.get("pending_user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    if verify_second_factor(user_id, code.strip()):
        complete_login(request, user_id)
        response = RedirectResponse(url="/", status_code=303)
        trust_device(response, user_id)
        return response
    return templates.TemplateResponse(request, "enterTOTP.html", {"error": "That code was not valid."})
