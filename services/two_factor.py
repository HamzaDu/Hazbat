"""Two-factor authentication: authenticators (TOTP), recovery codes and the time between checks.

Tables: tbl_user_2fa and tbl_user_recovery_codes, and twofa_interval in tbl_users.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time

import pyotp
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from core.db import get_admin_connection
from core.varreg import settings


def two_factor_cipher():
    """AES-256-CBC, with the key and the fixed IV derived from the two_factor_key setting."""
    settings.require("app", "two_factor_key")
    secret = settings.get("app", "two_factor_key").encode()
    key = hashlib.sha256(b"key" + secret).digest()
    iv = hashlib.sha256(b"iv" + secret).digest()[:16]
    return Cipher(algorithms.AES(key), modes.CBC(iv))


def encrypt_secret(secret):
    padder = padding.PKCS7(128).padder()
    padded = padder.update(secret.encode()) + padder.finalize()
    encryptor = two_factor_cipher().encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


def decrypt_secret(token):
    decryptor = two_factor_cipher().decryptor()
    padded = decryptor.update(base64.b64decode(token)) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode()


def totp_step(secret, code):
    """The time step a code is valid for (this one or a neighbour), or None."""
    code = code.replace(" ", "")
    if not (code.isascii() and code.isdigit()):
        return None
    now = int(time.time() // 30)
    totp = pyotp.TOTP(secret)
    for step in (now, now - 1, now + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def hash_recovery_code(code):
    normalised = code.replace("-", "").replace(" ", "").lower()
    return hashlib.sha256(normalised.encode()).hexdigest()


def has_confirmed_2fa(user_id):
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT EXISTS (SELECT 1 FROM tbl_user_2fa WHERE user_id = %s AND confirmed_at IS NOT NULL)", (user_id,))
        return cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()


def start_totp_enrolment(user_id, username):
    """Replaces any unconfirmed authenticator and unused recovery codes with new ones. Returns (secret, uri, codes)."""
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="BMAC")
    codes = []
    for _ in range(8):
        raw = secrets.token_hex(8)
        codes.append("-".join([raw[0:4], raw[4:8], raw[8:12], raw[12:16]]))
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM tbl_user_2fa WHERE user_id = %s AND confirmed_at IS NULL", (user_id,))
        cur.execute("DELETE FROM tbl_user_recovery_codes WHERE user_id = %s AND used_at IS NULL", (user_id,))
        cur.execute(
            "INSERT INTO tbl_user_2fa (user_id, method, name, data) VALUES (%s, 'totp', 'Authenticator', %s)",
            (user_id, json.dumps({"secret": encrypt_secret(secret), "last_step": 0}))
        )
        for code in codes:
            cur.execute("INSERT INTO tbl_user_recovery_codes (user_id, code_hash) VALUES (%s, %s)",
                        (user_id, hash_recovery_code(code)))
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return secret, uri, codes


def get_pending_totp(user_id, username):
    """The secret and URI of the user's unconfirmed authenticator, or None."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT data FROM tbl_user_2fa WHERE user_id = %s AND method = 'totp' AND confirmed_at IS NULL", (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        secret = decrypt_secret(row[0]["secret"])
        return secret, pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="BMAC")
    finally:
        cur.close()
        conn.close()


def confirm_totp(user_id, code):
    """Confirms the user's pending authenticator if the code is right. Returns True if it was confirmed."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, data FROM tbl_user_2fa WHERE user_id = %s AND method = 'totp' AND confirmed_at IS NULL", (user_id,))
        row = cur.fetchone()
        if not row:
            return False
        step = totp_step(decrypt_secret(row[1]["secret"]), code)
        if step is None:
            return False
        cur.execute(
            "UPDATE tbl_user_2fa SET confirmed_at = now(), last_used_at = now(), "
            "data = jsonb_set(data, '{last_step}', to_jsonb(%s::int)) WHERE id = %s",
            (step, row[0])
        )
        conn.commit()
        return True
    finally:
        cur.close()
        conn.close()


def get_trust_info(user_id):
    """(ID of the user's newest confirmed second-factor record, their interval in seconds),
    or None if the user has no confirmed second factor. A device cookie is valid for as long as the interval,
    and only while that record is the one it was issued for, so resetting two-factor cancels every cookie."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT (SELECT MAX(id) FROM tbl_user_2fa WHERE user_id = u.user_id AND confirmed_at IS NOT NULL), "
            "EXTRACT(EPOCH FROM u.twofa_interval) FROM tbl_users u WHERE u.user_id = %s",
            (user_id,)
        )
        row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        return row[0], int(row[1])
    finally:
        cur.close()
        conn.close()


def set_2fa_interval(user_id, interval):
    """Sets how long a successful check lasts, as a timedelta. A zero interval means a check at every login."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE tbl_users SET twofa_interval = %s WHERE user_id = %s", (interval, user_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()


def reset_2fa(user_id):
    """Removes the user's authenticators and recovery codes; they enrol again at their next login."""
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM tbl_user_2fa WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM tbl_user_recovery_codes WHERE user_id = %s", (user_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()


def verify_totp(cur, row_id, data, code):
    """True if the code is valid and newer than the last one used. Records its time step."""
    step = totp_step(decrypt_secret(data["secret"]), code)
    if step is None or step <= data["last_step"]:
        return False
    cur.execute(
        "UPDATE tbl_user_2fa SET last_used_at = now(), data = jsonb_set(data, '{last_step}', to_jsonb(%s::int)) WHERE id = %s",
        (step, row_id)
    )
    return True


def verify_second_factor(user_id, code):
    """True if the code is valid for one of the user's confirmed methods, or is an unused recovery code."""
    verifiers = {"totp": verify_totp}
    conn = get_admin_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, method, data FROM tbl_user_2fa WHERE user_id = %s AND confirmed_at IS NOT NULL", (user_id,))
        for row_id, method, data in cur.fetchall():
            if method in verifiers and verifiers[method](cur, row_id, data, code):
                conn.commit()
                return True
        cur.execute(
            "UPDATE tbl_user_recovery_codes SET used_at = now() "
            "WHERE user_id = %s AND code_hash = %s AND used_at IS NULL RETURNING id",
            (user_id, hash_recovery_code(code))
        )
        used = cur.fetchone() is not None
        conn.commit()
        return used
    finally:
        cur.close()
        conn.close()
