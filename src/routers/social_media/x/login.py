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
# from src.routers.social_media.x.controllers import rapidapi_get, extract_clean_user_info

router = APIRouter(prefix="/api/twitter", tags=["Twitter Login"])

# TEMP MEMORY STORE
TEMP_STORE = {}

# --------------------------------------
# HARDCODED TWITTER APP CREDENTIALS
# --------------------------------------
CLIENT_ID = "c3hTZmhyY1hCUTNUVXduMm0yVEo6MTpjaQ"
REDIRECT_URI = "https://backend-veris.skyserver.net.in/api/twitter/callback"


# --------------------------------------
# PKCE GENERATION
# --------------------------------------
def generate_pkce():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


# ---------------------------------------
# REFRESH TOKEN HANDLER
# ---------------------------------------
def get_valid_access_token(user: TwitterUser, db: Session):

    # valid token
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


# -------------------------------------------------
# STEP 1 — LOGIN ENDPOINT
# -------------------------------------------------
@router.get("/login")
def twitter_login():

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)

    TEMP_STORE["verifier"] = verifier
    TEMP_STORE["state"] = state

    scopes = "tweet.read users.read offline.access"

    auth_url = (
        "https://twitter.com/i/oauth2/authorize"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={quote(REDIRECT_URI)}"
        f"&scope={quote(scopes)}"
        f"&state={state}"
        f"&code_challenge={challenge}"
        f"&code_challenge_method=S256"
    )

    return RedirectResponse(auth_url)


# -------------------------------------------------
# STEP 2 — CALLBACK ENDPOINT
# -------------------------------------------------
@router.get("/callback")
def twitter_callback(request: Request, db: Session = Depends(get_db)):

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        return JSONResponse({"error": "Missing authorization code"}, status_code=400)

    if state != TEMP_STORE.get("state"):
        return JSONResponse({"error": "Invalid OAuth state"}, status_code=400)

    verifier = TEMP_STORE.get("verifier")

    # -----------------------------------
    # EXCHANGE CODE → ACCESS TOKEN
    # -----------------------------------
    token_url = "https://api.twitter.com/2/oauth2/token"

    payload = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
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

    # -----------------------------------
    # FETCH USER INFO
    # -----------------------------------
    user_info_url = "https://api.twitter.com/2/users/me"
    headers = {"Authorization": f"Bearer {access_token}"}

    # ❌ removed email (Twitter API does NOT support email)
    params = {"user.fields": "id,name,username,profile_image_url"}

    user_res = requests.get(user_info_url, headers=headers, params=params)

    if user_res.status_code != 200:
        return JSONResponse(
            {"error": "Failed to fetch user info", "details": user_res.text},
            status_code=400,
        )

    data = user_res.json().get("data", {})
    twitter_id = data["id"]

    # -----------------------------------
    # SAVE USER TO DATABASE
    # -----------------------------------
    user = db.query(TwitterUser).filter_by(id=twitter_id).first()

    if not user:
        user = TwitterUser(id=twitter_id)

    user.name = data.get("name")
    user.username = data.get("username")
    user.profile_image_url = data.get("profile_image_url")

    user.access_token = access_token
    user.refresh_token = refresh_token
    user.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    db.add(user)
    db.commit()

    jwt_token =({"user_id": twitter_id})

    # -------------------------------
    # REDIRECT TO FRONTEND
    # -------------------------------
    FRONTEND_SUCCESS_URL = "https://voxstrategix.com/auth/success"
    return RedirectResponse(
        f"{FRONTEND_SUCCESS_URL}?status=true&token={jwt_token}"
    )


# -------------------------------------------------
# FETCH SAVED USER WITH AUTO REFRESH
# -------------------------------------------------
@router.get("/user/{user_id}")
def get_user_data(user_id: str, db: Session = Depends(get_db)):

    user = db.query(TwitterUser).filter_by(id=user_id).first()

    if not user:
        return {"error": "User not found"}

    access_token = get_valid_access_token(user, db)

    return {
        "success": True,
        "id": user.id,
        "name": user.name,
        "username": user.username,
        "profile_image_url": user.profile_image_url,
    }



# ----------------------------------------------------------
# 3️⃣ PUBLIC USER TWEETS (ANY USER)
# ----------------------------------------------------------
RAPID_API_KEY = "3ce8c354e3msh22662032620dd62p121c70jsn15208e443454"
RAPID_API_HOST = "twitter241.p.rapidapi.com"


@router.get("/search")
def search_public_tweets(query: str, count: int = 20):
    url = "https://twitter241.p.rapidapi.com/search-v2"

    params = {
        "type": "Top",
        "count": str(count),
        "query": query,
    }

    headers = {
        "x-rapidapi-key": RAPID_API_KEY,
        "x-rapidapi-host": RAPID_API_HOST,
    }

    res = requests.get(url, headers=headers, params=params)

    if res.status_code != 200:
        return {"error": "Search failed", "details": res.text}

    data = res.json()

    clean_results = []

    # Extract important tweet info
    for item in data.get("data", {}).get("tweets", []):
        clean_results.append({
            "tweet_id": item.get("id"),
            "text": item.get("text"),
            "created_at": item.get("created_at"),
            "retweet_count": item.get("retweet_count"),
            "reply_count": item.get("reply_count"),
            "favorite_count": item.get("favorite_count"),
            "user": {
                "name": item.get("user", {}).get("name"),
                "username": item.get("user", {}).get("screen_name"),
                "profile_image": item.get("user", {}).get("profile_image_url_https"),
                "verified": item.get("user", {}).get("verified"),
            }
        })

    return {
        "success": True,
        "results": clean_results,
    }

# ----------------------------------------------------------
# GET IMPORTANT USER INFO (CLEANED)
# ----------------------------------------------------------
@router.get("/public/user-info/{username}")
def public_user_info(username: str):
    url = "https://twitter241.p.rapidapi.com/user"

    params = {"username": username}

    headers = {
        "x-rapidapi-key": RAPID_API_KEY,
        "x-rapidapi-host": RAPID_API_HOST,
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        return {
            "success": False,
            "error": response.text,
            "status_code": response.status_code
        }

    data = response.json()
    user = data.get("user", {}).get("result", {})

    # Clean user info
    legacy = user.get("legacy", {})
    professional = user.get("professional", {})

    cleaned = {
        "id": user.get("rest_id"),
        "name": legacy.get("name"),
        "username": legacy.get("screen_name"),
        "description": legacy.get("description"),
        "verified": user.get("is_blue_verified"),
        "created_at": legacy.get("created_at"),
        "followers": legacy.get("followers_count"),
        "following": legacy.get("friends_count"),
        "tweets_count": legacy.get("statuses_count"),
        "listed_count": legacy.get("listed_count"),
        "media_count": legacy.get("media_count"),
        "profile_image": legacy.get("profile_image_url_https"),
        "banner_image": legacy.get("profile_banner_url"),
        "location": legacy.get("location"),
        "website": legacy.get("url"),
        "professional": {
            "type": professional.get("professional_type"),
            "category": professional.get("category", [])
        },
        "highlights": user.get("highlights_info", {}),
        "super_follow_eligible": user.get("super_follow_eligible"),
        "creator_subscriptions_count": user.get("creator_subscriptions_count")
    }

    return {
        "success": True,
        "user": cleaned
    }
