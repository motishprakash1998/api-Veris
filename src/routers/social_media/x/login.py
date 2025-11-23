import os
import base64
import hashlib
import secrets
from urllib.parse import quote

import requests
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, JSONResponse

router = APIRouter(prefix="/api/twitter", tags=["Twitter Login"])

# TEMP MEMORY (use DB/Redis in production)
TEMP_STORE = {}


def generate_pkce():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


# -------------------------------------------------------
# 🔹 STEP 1 — LOGIN START
# -------------------------------------------------------
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


# -------------------------------------------------------
# 🔹 STEP 2 — CALLBACK + TOKEN + USER INFO
# -------------------------------------------------------
@router.get("/callback")
def twitter_callback(request: Request):

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        return JSONResponse({"error": "Missing authorization code"}, status_code=400)

    if state != TEMP_STORE.get("state"):
        return JSONResponse({"error": "Invalid OAuth state"}, status_code=400)

    verifier = TEMP_STORE.get("verifier")
    redirect_uri = TEMP_STORE.get("redirect_uri")
    client_id = os.getenv("TWITTER_CLIENT_ID", "c3hTZmhyY1hCUTNUVXduMm0yVEo6MTpjaQ")

    # ----------------------------------------
    # 🔄 EXCHANGE CODE → TOKEN
    # ----------------------------------------
    token_url = "https://api.twitter.com/2/oauth2/token"

    payload = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    token_res = requests.post(token_url, data=payload, headers=headers)

    if token_res.status_code != 200:
        return JSONResponse(
            {"error": "Token request failed", "details": token_res.text},
            status_code=400,
        )

    token_data = token_res.json()
    access_token = token_data["access_token"]

    # ----------------------------------------
    # 🔍 FETCH USER INFO
    # ----------------------------------------
    user_info_url = "https://api.twitter.com/2/users/me"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"user.fields": "id,name,username,profile_image_url"}

    user_res = requests.get(user_info_url, headers=headers, params=params)

    if user_res.status_code != 200:
        return JSONResponse(
            {"error": "Failed to fetch user info", "details": user_res.text},
            status_code=400,
        )

    user_data = user_res.json()

    # ------------------------------------------------
    # 🎉 RETURN CLEAN JSON (for frontend)
    # ------------------------------------------------
    return JSONResponse(
        {
            "success": True,
            "user": user_data.get("data", {}),
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token"),
        }
    )
