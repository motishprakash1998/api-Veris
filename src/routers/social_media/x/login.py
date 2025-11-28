import os
import base64
import hashlib
import secrets
from urllib.parse import quote_plus
from datetime import datetime, timedelta

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

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)

    TEMP_STORE[state] = {
        "verifier": verifier,
        "redirect_uri": REDIRECT_URI
    }

    scopes = "tweet.read users.read offline.access email.read"

    encoded_redirect = quote_plus(REDIRECT_URI)

    auth_url = (
        "https://twitter.com/i/oauth2/authorize"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={encoded_redirect}"
        f"&scope={quote_plus(scopes)}"
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

    if not code or state not in TEMP_STORE:
        return JSONResponse({"error": "OAuth failed"}, status_code=400)

    verifier = TEMP_STORE[state]["verifier"]
    redirect_uri = TEMP_STORE[state]["redirect_uri"]

    token_url = "https://api.twitter.com/2/oauth2/token"

    payload = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    res = requests.post(token_url, data=payload, headers=headers)

    if res.status_code != 200:
        return JSONResponse({"error": "Token exchange failed", "raw": res.text}, status_code=400)

    tokens = res.json()

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens["expires_in"]

    headers = {"Authorization": f"Bearer {access_token}"}

    user_res = requests.get(
        "https://api.twitter.com/2/users/me",
        headers=headers,
        params={"user.fields": "id,name,username,profile_image_url,email"}
    )

    user_data = user_res.json().get("data", {})

    user = db.query(TwitterUser).filter_by(id=user_data["id"]).first()

    if not user:
        user = TwitterUser(id=user_data["id"])

    user.name = user_data.get("name")
    user.username = user_data.get("username")
    user.profile_image_url = user_data.get("profile_image_url")
    user.email = user_data.get("email")

    user.access_token = access_token
    user.refresh_token = refresh_token
    user.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    db.add(user)
    db.commit()

    return {"success": True, "id": user.id}


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
