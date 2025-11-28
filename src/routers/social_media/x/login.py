import os
import base64
import hashlib
import secrets
from urllib.parse import quote_plus
from datetime import datetime, timedelta
from urllib.parse import quote

import requests
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from src.routers.social_media.models.x_models import TwitterUser
from src.database import get_db

router = APIRouter(prefix="/api/twitter", tags=["Twitter Login"])

TEMP_STORE = {}  # Replace with Redis later

# -----------------------------
# HARDCODED CREDENTIALS
# -----------------------------
CLIENT_ID = "c3hTZmhyY1hCUTNUVXduMm0yVEo6MTpjaQ"
REDIRECT_URI = "https://backend-veris.skyserver.net.in/api/twitter/callback"


# ----------------------------------------------------
# PKCE GENERATION
# ----------------------------------------------------
def generate_pkce():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


# ----------------------------------------------------
# REFRESH TOKEN HANDLER
# ----------------------------------------------------
def get_valid_access_token(user: TwitterUser, db: Session):

    if user.token_expires_at and user.token_expires_at > datetime.utcnow():
        return user.access_token

    refresh_url = "https://api.twitter.com/2/oauth2/token"

    payload = {
        "refresh_token": user.refresh_token,
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    res = requests.post(refresh_url, data=payload, headers=headers)

    if res.status_code != 200:
        print("TOKEN REFRESH FAILED:", res.text)
        return None

    data = res.json()

    user.access_token = data["access_token"]
    user.refresh_token = data.get("refresh_token", user.refresh_token)
    user.token_expires_at = datetime.utcnow() + timedelta(seconds=data["expires_in"])

    db.commit()

    return user.access_token


# ----------------------------------------------------
# STEP 1 — LOGIN (Redirect to Twitter)
# ----------------------------------------------------
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

# ----------------------------------------------------
# STEP 2 — CALLBACK
# ----------------------------------------------------
@router.get("/callback")
def twitter_callback(request: Request, db: Session = Depends(get_db)):

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        return JSONResponse({"error": "Missing authorization code"}, status_code=400)

    if state != TEMP_STORE.get("state"):
        return JSONResponse({"error": "Invalid OAuth state"}, status_code=400)

    verifier = TEMP_STORE.get("verifier")
    redirect_uri = TEMP_STORE.get("redirect_uri")
    client_id = CLIENT_ID

    # ----------------------------------------
    # EXCHANGE CODE → TOKEN
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
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 7200)

    # ----------------------------------------
    # FETCH USER INFO
    # ----------------------------------------
    user_info_url = "https://api.twitter.com/2/users/me"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"user.fields": "id,name,username,profile_image_url,email"}

    user_res = requests.get(user_info_url, headers=headers, params=params)

    if user_res.status_code != 200:
        return JSONResponse(
            {"error": "Failed to fetch user info", "details": user_res.text},
            status_code=400,
        )

    user_data = user_res.json().get("data", {})

    # ----------------------------------------
    # SAVE USER IN DATABASE
    # ----------------------------------------
    twitter_id = user_data["id"]

    user = db.query(TwitterUser).filter_by(id=twitter_id).first()

    if not user:
        user = TwitterUser(id=twitter_id)

    user.name = user_data.get("name")
    user.username = user_data.get("username")
    user.profile_image_url = user_data.get("profile_image_url")
    user.email = user_data.get("email")

    user.access_token = access_token
    user.refresh_token = refresh_token
    user.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    db.add(user)
    db.commit()

    # ----------------------------------------
    # FRONTEND RESPONSE
    # ----------------------------------------
    return {
        "success": True,
        "id": twitter_id,
        "name": user.name,
        "username": user.username,
        "profile_image_url": user.profile_image_url,
        "email": user.email,
    }


# ----------------------------------------------------
# USER DATA WITH AUTO REFRESH
# ----------------------------------------------------
@router.get("/user/{user_id}")
def get_user_data(user_id: str, db: Session = Depends(get_db)):

    user = db.query(TwitterUser).filter_by(id=user_id).first()

    if not user:
        return {"error": "User not found"}

    get_valid_access_token(user, db)

    return {
        "success": True,
        "id": user.id,
        "name": user.name,
        "username": user.username,
        "email": user.email,
        "profile_image_url": user.profile_image_url,
    }
