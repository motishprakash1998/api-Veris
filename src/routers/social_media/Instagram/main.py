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
@router.get("/login")
def instagram_login():

    scope = (
    "pages_show_list,"
    "pages_manage_metadata,"
    "pages_read_engagement,"
    "pages_read_user_content,"
    "pages_manage_posts"
)


    auth_url = (
        "https://www.facebook.com/v21.0/dialog/oauth"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={scope}"
        f"&response_type=code"
    )

    return RedirectResponse(url=auth_url)



# -------------------------------------------------------
# 🔹 STEP 2 — CALLBACK + EXCHANGE TOKEN
# -------------------------------------------------------
@router.get("/callback")
def instagram_callback(request: Request):

    code = request.query_params.get("code")

    if not code:
        return {"error": "Missing code"}

    token_url = "https://graph.facebook.com/v21.0/oauth/access_token"

    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code
    }

    res = requests.get(token_url, params=payload)

    data = res.json()

    return {
        "success": True,
        "access_token": data
    }
