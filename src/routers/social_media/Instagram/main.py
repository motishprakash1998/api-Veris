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
CLIENT_ID = "2020018448748214"
CLIENT_SECRET = "a4cf677f7bd5f34af3597c23490b294a"
REDIRECT_URI = "https://backend-veris.skyserver.net.in/api/instagram/callback"


# -------------------------------------------------------
# 🔹 STEP 1 — LOGIN (Redirect to Instagram)
# -------------------------------------------------------
@router.get("/login")
def instagram_login():

    scope = (
        "instagram_business_basic,"
        "instagram_business_manage_messages,"
        "instagram_business_manage_comments,"
        "instagram_business_content_publish,"
        "instagram_business_manage_insights"
    )

    auth_url = (
        "https://www.instagram.com/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={scope}"
        f"&response_type=code"
        f"&force_reauth=true"
    )

    return RedirectResponse(url=auth_url)


# -------------------------------------------------------
# 🔹 STEP 2 — CALLBACK + EXCHANGE TOKEN
# -------------------------------------------------------
@router.get("/callback")
def instagram_callback(request: Request):

    code = request.query_params.get("code")

    if not code:
        return JSONResponse({"error": "No 'code' provided"}, status_code=400)

    token_url = "https://api.instagram.com/oauth/access_token"

    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code": code
    }

    res = requests.post(token_url, data=payload)

    if res.status_code != 200:
        return JSONResponse(
            {"error": "Token exchange failed", "raw": res.text},
            status_code=400
        )

    token_data = res.json()

    # Clean response for frontend
    return JSONResponse({
        "success": True,
        "message": "Instagram Login Successful",
        "access_token_response": token_data
    })
