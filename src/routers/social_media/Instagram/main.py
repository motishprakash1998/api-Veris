import requests
from . import controller
from src.database import get_db
from sqlalchemy.orm import Session
from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks, Request
from fastapi.responses import RedirectResponse, JSONResponse

router = APIRouter(
    prefix="/api/instagram",
    tags=["Instagram Services"],
    responses={404: {"description": "Not found"}},
)

@router.get("/")
def root():
    return {"msg": "Instagram scraper router. Use /validate?username=<username>"}


@router.get("/validate", summary="Validate Instagram username and return profile info")
def validate(
    username: str = Query(..., description="Instagram username to lookup"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """Fetch Instagram profile and schedule background fetch for posts/metrics."""
    try:
        profile = controller.fetch_instagram_profile(username, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except requests.exceptions.RequestException as re:
        raise HTTPException(status_code=502, detail=str(re))

    # Kick off background job to fetch posts
    background_tasks.add_task(controller.fetch_instagram_posts, username, db)

    response = {
        "success": True,
        "status": 200,
        "message": f"Fetched profile data for {username} successfully.",
        "data": profile,
    }
    return response


# Instagram App Config
CLIENT_ID = "2007595690062087"
CLIENT_SECRET = "61175cf6e37f68bf12d1ea59749e9fe9"
REDIRECT_URI = "https://backend-veris.skyserver.net.in/api/instagram/callback"


# -------------------------------------------------------
# 🔹 STEP 1 — LOGIN (Redirect to Instagram)
# -------------------------------------------------------
from urllib.parse import urlencode
@router.get("/login")
def instagram_login():
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "user_profile",
        "response_type": "code",
    }

    auth_url = "https://api.instagram.com/oauth/authorize?" + urlencode(params)

    return RedirectResponse(url=auth_url)



# -------------------------------------------------------
# 🔹 STEP 2 — CALLBACK + EXCHANGE TOKEN
# -------------------------------------------------------
@router.get("/callback")
def instagram_callback(request: Request):

    code = request.query_params.get("code")
    if not code:
        return {"error": "Missing code"}

    token_url = "https://api.instagram.com/oauth/access_token"

    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    response = requests.post(token_url, data=payload)
    token_data = response.json()

    if "access_token" not in token_data:
        return {
            "error": "Token exchange failed",
            "response": token_data
        }

    return {
        "success": True,
        "access_token": token_data["access_token"],
        "user_id": token_data.get("user_id")
    }
