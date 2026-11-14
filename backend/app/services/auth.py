import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

SESSION_COOKIE = "bm_session"


@dataclass(frozen=True)
class GuestIdentity:
    id: str
    display_name: str


def _encode(payload: dict[str, str]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> dict[str, str]:
    padded = value + "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))


def _signature(payload: str) -> str:
    secret = get_settings().app_secret.encode("utf-8")
    return hmac.new(secret, payload.encode("ascii"), hashlib.sha256).hexdigest()


def issue_guest_token(
    guest_id: str | None = None, display_name: str = ""
) -> tuple[GuestIdentity, str]:
    """Issue a signed, cookie-backed identity without changing the guest id."""
    identity = GuestIdentity(id=guest_id or secrets.token_urlsafe(12), display_name=display_name)
    payload = _encode({"id": identity.id, "name": identity.display_name})
    return identity, f"{payload}.{_signature(payload)}"


def identity_from_token(token: str | None) -> GuestIdentity:
    if not token or "." not in token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão ausente.")
    try:
        if len(token) > 4096:
            raise ValueError("Token exceeds cookie size")
        payload, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(_signature(payload), signature):
            raise ValueError("Invalid signature")
        data = _decode(payload)
        if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not data["id"] or not isinstance(data.get("name"), str):
            raise ValueError("Invalid identity")
        return GuestIdentity(id=data["id"], display_name=data["name"])
    except (KeyError, TypeError, UnicodeError, ValueError, binascii.Error) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida.") from error


def current_identity(request: Request) -> GuestIdentity:
    """Accept the httpOnly cookie locally and a bearer token cross-origin.

    Render gives the static site and API different `*.onrender.com` origins.
    Browsers can therefore reject the cookie as third-party state. The signed
    bearer fallback keeps the same server-validated identity without relying
    on that cross-origin cookie behavior.
    """
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return identity_from_token(authorization[7:].strip())
    return identity_from_token(request.cookies.get(SESSION_COOKIE))
