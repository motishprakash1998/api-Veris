import os
import base64
import hashlib
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse

router = APIRouter(
    prefix="/api/twitter",
    tags=["Twitter Login"],
)

# Temporary PKCE + state store
TEMP_STORE = {}


def generate_pkce():
    """Generate PKCE verifier + challenge."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


@router.get("/login")
def login():
    """Start Twitter OAuth login."""
    client_id = os.getenv("X_CLIENT_ID", "c3hTZmhyY1hCUTNUVXduMm0yVEo6MTpjaQ")

    # YOUR FIXED AND CORRECT REDIRECT
    redirect_uri = "https://backend-veris.skyserver.net.in/api/twitter/callback"

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)

    TEMP_STORE["verifier"] = verifier
    TEMP_STORE["state"] = state

    scopes = "tweet.read users.read offline.access"

    auth_url = (
        "https://twitter.com/i/oauth2/authorize"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={quote(redirect_uri)}"
        f"&scope={quote(scopes)}"
        f"&state={state}"
        f"&code_challenge={challenge}"
        f"&code_challenge_method=S256"
    )

    return RedirectResponse(url=auth_url)


@router.get("/callback")
def callback(request: Request):
    """Twitter redirect callback."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        return HTMLResponse("<h3>Error: Missing 'code' from Twitter</h3>")

    if state != TEMP_STORE.get("state"):
        return HTMLResponse("<h3>Error: Invalid OAuth state</h3>")

    # Everything is correct — ready for token exchange
    return HTMLResponse(f"<h2>OAuth Success</h2><pre>code: {code}</pre>")
