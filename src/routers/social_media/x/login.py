import os
import base64
import hashlib
import secrets
from urllib.parse import quote
from datetime import datetime, timedelta

import requests
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from src.routers.social_media.models.x_models import TwitterUser
from src.database import get_db

router = APIRouter(prefix="/api/twitter", tags=["Twitter Login"])

TEMP_STORE = {}   # Replace with Redis later


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
# TOKEN AUTO REFRESH SYSTEM
# ----------------------------------------------------
def get_valid_access_token(user: TwitterUser, db: Session):
    # Still valid
    if user.token_expires_at and user.token_expires_at > datetime.utcnow():
        return user.access_token

    # Expired - refresh
    url = "https://api.twitter.com/2/oauth2/token"
    payload = {
        "refresh_token": user.refresh_token,
        "grant_type": "refresh_token",
        "client_id": os.getenv("TWITTER_CLIENT_ID"),
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    res = requests.post(url, data=payload, headers=headers)

    if res.status_code != 200:
        print("Refresh failed:", res.text)
        return None

    token_data = res.json()

    user.access_token = token_data["access_token"]
    user.refresh_token = token_data.get("refresh_token", user.refresh_token)
    user.token_expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])

    db.commit()
    return user.access_token


# ----------------------------------------------------
# STEP 1 — LOGIN (Redirect to Twitter)
# ----------------------------------------------------
@router.get("/login")
def twitter_login():
    client_id = os.getenv("TWITTER_CLIENT_ID","c3hTZmhyY1hCUTNUVXduMm0yVEo6MTpjaQ")

    redirect_uri = "https://backend-veris.skyserver.net.in/api/twitter/callback"

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)

    TEMP_STORE[state] = {
        "verifier": verifier,
        "redirect_uri": redirect_uri
    }

    scopes = "tweet.read users.read offline.access email.read"

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
# STEP 2 — CALLBACK (Save User in DB + Tokens)
# ----------------------------------------------------
@router.get("/callback")
def twitter_callback(request: Request, db: Session = Depends(get_db)):
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or state not in TEMP_STORE:
        return JSONResponse({"error": "Invalid OAuth"}, status_code=400)

    verifier = TEMP_STORE[state]["verifier"]
    redirect_uri = TEMP_STORE[state]["redirect_uri"]

    client_id = os.getenv("TWITTER_CLIENT_ID")

    # ---- Exchange code → token ----
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
        return JSONResponse({"error": "Token failed", "details": token_res.text}, status_code=400)

    token_data = token_res.json()
    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data["expires_in"]

    # ---- Fetch user info ----
    headers = {"Authorization": f"Bearer {access_token}"}

    user_res = requests.get(
        "https://api.twitter.com/2/users/me",
        headers=headers,
        params={"user.fields": "id,name,username,profile_image_url,email"},
    )

    user_info = user_res.json().get("data", {})

    # ---- Save in DB ----
    user = db.query(TwitterUser).filter_by(id=user_info["id"]).first()

    if not user:
        user = TwitterUser(id=user_info["id"])

    user.name = user_info.get("name")
    user.username = user_info.get("username")
    user.profile_image_url = user_info.get("profile_image_url")
    user.email = user_info.get("email")

    user.access_token = access_token
    user.refresh_token = refresh_token
    user.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    db.add(user)
    db.commit()

    return {
        "success": True,
        "id": user.id
    }


# ----------------------------------------------------
# FRONTEND CALL — Get User Data (Auto Token Refresh)
# ----------------------------------------------------
@router.get("/user/{user_id}")
def get_user_data(user_id: str, db: Session = Depends(get_db)):
    user = db.query(TwitterUser).filter_by(id=user_id).first()

    if not user:
        return {"error": "User not found"}

    # Auto refresh token
    get_valid_access_token(user, db)

    return {
        "success": True,
        "id": user.id,
        "name": user.name,
        "username": user.username,
        "email": user.email,
        "profile_image_url": user.profile_image_url,
    }
