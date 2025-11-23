import os
import base64
import hashlib
import secrets
from urllib.parse import quote

import requests
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse

router = APIRouter(prefix="/api/twitter", tags=["Twitter Login"])

# In-memory PKCE & state storage (store in DB/Redis in production)
TEMP_STORE = {}


def generate_pkce():
    """Generate PKCE verifier + challenge."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


# ----------------------------------------
# 🔹 STEP 1 — LOGIN START
# ----------------------------------------
@router.get("/login")
def twitter_login():
    client_id = os.getenv("TWITTER_CLIENT_ID", "c3hTZmhyY1hCUTNUVXduMm0yVEo6MTpjaQ")

    redirect_uri = "https://backend-veris.skyserver.net.in/api/twitter/callback"

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)

    TEMP_STORE["verifier"] = verifier
    TEMP_STORE["state"] = state
    TEMP_STORE["redirect_uri"] = redirect_uri

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


# ----------------------------------------
# 🔹 STEP 2 — CALLBACK + TOKEN EXCHANGE
# ----------------------------------------
@router.get("/callback")
def twitter_callback(request: Request):

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        return HTMLResponse("<h3>Error: Missing 'code' from Twitter</h3>")

    if state != TEMP_STORE.get("state"):
        return HTMLResponse("<h3>Error: Invalid OAuth state</h3>")

    # PKCE verifier
    verifier = TEMP_STORE.get("verifier")
    redirect_uri = TEMP_STORE.get("redirect_uri")

    client_id = os.getenv("X_CLIENT_ID", "c3hTZmhyY1hCUTNUVXduMm0yVEo6MTpjaQ")

    # -------------------------------
    # 🔄 STEP 3 — Exchange Code for Token
    # -------------------------------
    token_url = "https://api.twitter.com/2/oauth2/token"

    payload = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(token_url, data=payload, headers=headers)

    if response.status_code != 200:
        return HTMLResponse(
            f"<h3>Token Exchange Failed</h3><pre>{response.text}</pre>"
        )

    token_data = response.json()

    # -------------------------------
    # 🎉 SUCCESS
    # -------------------------------
    return HTMLResponse(
        f"""
        <h2>Twitter OAuth Success</h2>
        <h3>Access Token Received!</h3>
        <pre>{token_data}</pre>
        """
    )
