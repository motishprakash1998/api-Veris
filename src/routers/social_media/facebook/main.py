import os
import re
import jwt
import json
import httpx
import requests
from . import controller
from sqlalchemy import func 
from dotenv import load_dotenv
from src.database import get_db
from typing import Optional,List
from sqlalchemy.orm import Session
from urllib.parse import quote, unquote
from urllib.parse import urlparse,parse_qs, quote
from fastapi.responses import RedirectResponse, JSONResponse
from src.routers.social_media.models.facebook_models import FacebookUser
from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks,Request, status
from src.routers.user_management.models.users import User
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from src.utils.jwt import ( get_email_from_token)
import logging

logger = logging.getLogger(__name__)

load_dotenv()


router = APIRouter(
    prefix="/api/facebook",
    tags=["Facebook Services"],
    responses={404: {"description": "Not found"}},
)

@router.get("/")
def root():
    return {"msg": "Facebook scraper router. Use /validate?username=<username>"}


@router.get("/validate", summary="Validate Facebook username and return profile info")
def validate(
    username: str = Query(..., description="Facebook username to lookup"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """Fetch Facebook profile and schedule background fetch for posts/metrics."""
    try:
        profile = controller.fetch_facebook_profile(username, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except requests.exceptions.RequestException as re:
        raise HTTPException(status_code=502, detail=str(re))

    # Kick off background job to fetch posts
    # background_tasks.add_task(controller.fetch_facebook_profile, username, db)

    response = {
        "success": True,
        "status": 200,
        "message": f"Fetched profile data for {username} successfully.",
        "data": profile,
    }
    return response


## PPCA
# ====================================================
# FACEBOOK CONFIGURATION
# ====================================================
APP_ID = os.getenv("POST_FB_APP_ID", "2007595690062087")
APP_SECRET = os.getenv("POST_FB_APP_SECRET", "61175cf6e37f68bf12d1ea59749e9fe9")
ACCESS_TOKEN = os.getenv("POST_FB_ACCESS_TOKEN", f"{APP_ID}|{APP_SECRET}")

GRAPH_API_URL = "https://graph.facebook.com/v19.0"
POSTS_PER_PAGE = 10
REQUEST_TIMEOUT = 8  # seconds


# ====================================================
# HELPER FUNCTIONS
# ====================================================

def extract_page_name(input_str: str) -> str:
    """
    Extract page username/ID from either:
      - A Facebook URL: https://www.facebook.com/PageName/
      - Or a plain page name: PageName
    """
    if not input_str:
        raise HTTPException(status_code=400, detail="Page name or URL required")

    # If input looks like a URL
    if input_str.startswith("http"):
        parsed = urlparse(input_str)
        path = parsed.path.strip("/")
        if not path:
            raise HTTPException(status_code=400, detail="Invalid Facebook URL format")
        # Handle cases like "/profile.php?id=123456"
        match = re.search(r"id=(\d+)", parsed.query)
        if match:
            return match.group(1)
        return path.split("/")[0]  # first segment = page handle
    return input_str.strip()


def fetch_page_basic(page_name: str):
    params = {
        "fields": "id,name,about,category,link,fan_count,followers_count,picture.width(720).height(720)",
        "access_token": ACCESS_TOKEN
    }
    try:
        r = requests.get(f"{GRAPH_API_URL}/{page_name}", params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()

        # Extract clean profile picture URL (safely)
        picture_url = (
            data.get("picture", {})
            .get("data", {})
            .get("url", None)
        )

        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "about": data.get("about"),
            "category": data.get("category"),
            "link": data.get("link"),
            "fan_count": data.get("fan_count"),
            "followers_count": data.get("followers_count"),
            "profile_picture": picture_url
        }

    except requests.exceptions.RequestException as e:
        return {"error": {"message": f"Network error: {str(e)}"}}
    except Exception as e:
        return {"error": {"message": f"Unexpected error: {str(e)}"}}


def fetch_posts_for_page(page_id, after_cursor=None, before_cursor=None, limit=POSTS_PER_PAGE):
    post_fields = (
        "id,message,created_time,permalink_url,full_picture,"
        "attachments{media_type,media,target,url},"
        "reactions.summary(true).limit(0),"
        "comments.summary(true).limit(0),"
        "shares"
    )

    params = {
        "fields": post_fields,
        "access_token": ACCESS_TOKEN,
        "limit": limit
    }

    if after_cursor:
        params["after"] = after_cursor
    if before_cursor:
        params["before"] = before_cursor

    try:
        r = requests.get(f"{GRAPH_API_URL}/{page_id}/posts", params=params, timeout=REQUEST_TIMEOUT)
        return r.json()
    except Exception as e:
        return {"error": {"message": str(e)}}


def normalize_post(post):
    message = post.get("message", "")
    created_time = post.get("created_time", "")
    permalink = post.get("permalink_url", "#")
    full_picture = post.get("full_picture")

    if not full_picture:
        attachments = post.get("attachments", {}).get("data", [])
        if attachments:
            a0 = attachments[0]
            full_picture = (
                (a0.get("media") or {}).get("image", {}).get("src")
                or a0.get("url")
                or None
            )

    reactions_count = post.get("reactions", {}).get("summary", {}).get("total_count", 0)
    comments_count = post.get("comments", {}).get("summary", {}).get("total_count", 0)
    shares_count = post.get("shares", {}).get("count", 0)

    return {
        "id": post.get("id"),
        "message": message,
        "created_time": created_time,
        "permalink_url": permalink,
        "full_picture": full_picture,
        "reactions_count": reactions_count,
        "comments_count": comments_count,
        "shares_count": shares_count
    }


# ====================================================
# ROUTES (API ENDPOINTS)
# ====================================================

@router.get("/page/info")
def get_page_info(
    input_value: str = Query(..., description="Facebook Page name or full URL"),
    db: Session = Depends(get_db),
):
    """
    🔹 Get basic information about a Facebook Page.
    Accepts:
    - Plain name: LalchandKatariaOfficial
    - Full URL:   https://www.facebook.com/LalchandKatariaOfficial/
    """

    try:
        # -------------------------------
        # Extract page name
        # -------------------------------
        page_name = extract_page_name(input_value)
        if not page_name:
            return JSONResponse(
                status_code=200,
                content={
                    "status": False,
                    "message": "Invalid Facebook page name or URL",
                    "page": None,
                },
            )

        # -------------------------------
        # Fetch page info
        # -------------------------------
        page_data = fetch_page_basic(page_name)

        if not page_data:
            return JSONResponse(
                status_code=200,
                content={
                    "status": False,
                    "message": "Unable to fetch Facebook page information",
                    "page": None,
                },
            )

        if page_data.get("error"):
            return JSONResponse(
                status_code=200,
                content={
                    "status": False,
                    "message": page_data["error"].get("message", "Facebook API error"),
                    "page": None,
                },
            )

        # -------------------------------
        # Validate page ID
        # -------------------------------
        page_id = page_data.get("id")
        if not page_id:
            return JSONResponse(
                status_code=200,
                content={
                    "status": False,
                    "message": "Could not determine Facebook Page ID",
                    "page": None,
                },
            )

        # -------------------------------
        # Success response
        # -------------------------------
        return JSONResponse(
            status_code=200,
            content={
                "status": True,
                "page": {
                    "id": page_data.get("id"),
                    "name": page_data.get("name", ""),
                    "about": page_data.get("about"),
                    "category": page_data.get("category"),
                    "link": page_data.get("link"),
                    "fan_count": page_data.get("fan_count"),
                    "followers_count": page_data.get("followers_count"),
                    "picture_url": page_data.get("profile_picture"),
                },
            },
        )

    except Exception:
        # -------------------------------
        # Catch-all safety net
        # -------------------------------
        logger.exception("Error fetching Facebook page info")

        return JSONResponse(
            status_code=200,
            content={
                "status": False,
                "message": "Something went wrong while fetching page information",
                "page": None,
            },
        )

# --- Endpoint ---
@router.get("/page/posts")
def get_page_posts(
    input_value: str = Query(..., description="Facebook Page name or full URL"),
    after: Optional[str] = Query(None, description="Pagination cursor for next page"),
    before: Optional[str] = Query(None, description="Pagination cursor for previous page"),
    limit: int = Query(10, ge=1, le=100, description="Number of posts per page"),
    db: Session = Depends(get_db),
):
    """
    Fetch Facebook page info and recent posts.
    Supports pagination via 'after' and 'before' cursors.
    """

    try:
        # -------------------------------
        # Extract page name
        # -------------------------------
        page_name = extract_page_name(input_value)
        if not page_name:
            return JSONResponse(
                status_code=200,
                content={
                    "status": False,
                    "message": "Invalid Facebook page name or URL",
                    "page": None,
                    "posts": [],
                },
            )

        # -------------------------------
        # Fetch page basic info
        # -------------------------------
        page_basic = fetch_page_basic(page_name)

        if not page_basic:
            return JSONResponse(
                status_code=200,
                content={
                    "status": False,
                    "message": "Unable to fetch Facebook page information",
                    "page": None,
                    "posts": [],
                },
            )

        if page_basic.get("error"):
            return JSONResponse(
                status_code=200,
                content={
                    "status": False,
                    "message": page_basic["error"].get("message", "Facebook API error"),
                    "page": None,
                    "posts": [],
                },
            )

        # -------------------------------
        # Validate page ID
        # -------------------------------
        page_id = page_basic.get("id")
        if not page_id:
            return JSONResponse(
                status_code=200,
                content={
                    "status": False,
                    "message": "Could not determine Facebook Page ID",
                    "page": None,
                    "posts": [],
                },
            )

        # -------------------------------
        # Fetch posts
        # -------------------------------
        posts_res = fetch_posts_for_page(
            page_id,
            after_cursor=after,
            before_cursor=before,
            limit=limit,
        )

        if not posts_res:
            return JSONResponse(
                status_code=200,
                content={
                    "status": False,
                    "message": "Unable to fetch page posts",
                    "page": None,
                    "posts": [],
                },
            )

        if posts_res.get("error"):
            return JSONResponse(
                status_code=200,
                content={
                    "status": False,
                    "message": posts_res["error"].get("message", "Facebook API error"),
                    "page": None,
                    "posts": [],
                },
            )

        # -------------------------------
        # Normalize posts
        # -------------------------------
        raw_posts = posts_res.get("data", [])
        posts = [normalize_post(post) for post in raw_posts]

        # -------------------------------
        # Pagination cursors
        # -------------------------------
        paging = posts_res.get("paging", {})
        cursors = paging.get("cursors", {}) if paging else {}

        next_cursor = cursors.get("after")
        prev_cursor = cursors.get("before")

        # -------------------------------
        # Success response
        # -------------------------------
        return JSONResponse(
            status_code=200,
            content={
                "status": True,
                "page": {
                    "id": page_basic.get("id"),
                    "name": page_basic.get("name"),
                    "about": page_basic.get("about"),
                    "category": page_basic.get("category"),
                    "link": page_basic.get("link"),
                    "fan_count": page_basic.get("fan_count"),
                    "followers_count": page_basic.get("followers_count"),
                    "picture_url": page_basic.get("profile_picture"),
                },
                "posts": posts,
                "next_cursor": next_cursor,
                "prev_cursor": prev_cursor,
                "has_next": bool(next_cursor),
                "has_previous": bool(prev_cursor),
            },
        )

    except Exception as e:
        # -------------------------------
        # Catch-all (never crash API)
        # -------------------------------
        logger.exception("Error fetching Facebook page posts")

        return JSONResponse(
            status_code=200,
            content={
                "status": False,
                "message": "Something went wrong while processing the request",
                "page": None,
                "posts": [],
            },
        )

    
# ====== CONFIG (change these or set env vars) ======
LOGIN_APP_ID = os.environ.get("FB_APP_ID", "2037441327057334")
LOGIN_APP_SECRET = os.environ.get("FB_APP_SECRET", "f6579b31b6f6186aecda29b5be8a4481")
LOGIN_REDIRECT_URI = os.environ.get("FB_REDIRECT_URI", "https://backend-veris.skyserver.net.in/api/facebook/callback")
FB_VERSION = os.environ.get("FB_VERSION", "v16.0")

REQUIRED_SCOPE = ["email", "public_profile"]
OPTIONAL_SCOPES = {
    "user_link": "Access user profile URL (link)",
    "user_posts": "Read user timeline posts (user_posts)",
    "user_photos": "Read user photos (user_photos)",
    "user_location": "Access user location (user_location)",
}


# ---------- LOGIN ----------
# Scope configuration
REQUIRED_SCOPE = ["public_profile"]
OPTIONAL_SCOPES = {
    "email",
    "user_posts",
    "user_photos",
    "user_location",
    "user_link",
}


# URL to redirect to on successful login (frontend)
FRONTEND_SUCCESS_URL = "https://voxstrategix.com/auth/facebook/success"

# URL to redirect to on login failure (frontend)
@router.get("/login")
async def facebook_login(
    request: Request,
    token: str = Query(..., description="JWT access token"),
):
    # -------------------------------
    # Read optional scopes from query
    # -------------------------------
    raw_qs = urlparse(str(request.url)).query
    parsed = parse_qs(raw_qs)
    chosen: List[str] = parsed.get("scopes", [])

    scopes = list(REQUIRED_SCOPE)
    for c in chosen:
        if c in OPTIONAL_SCOPES and c not in scopes:
            scopes.append(c)

    # -------------------------------
    # Encode token into state
    # -------------------------------
    state = quote(token)
    scope_str = ",".join(scopes)

    auth_url = (
        f"https://www.facebook.com/{FB_VERSION}/dialog/oauth?"
        f"client_id={LOGIN_APP_ID}"
        f"&redirect_uri={quote(LOGIN_REDIRECT_URI)}"
        f"&scope={quote(scope_str)}"
        f"&response_type=code"
        f"&state={state}"
    )

    # optional (debug / audit)
    request.session["requested_scopes"] = scopes

    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


# ---------- CALLBACK ----------
@router.get("/callback")
async def facebook_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    # -------------------------------
    # Decode token from state
    # -------------------------------
    raw_token = unquote(state)
    email = get_email_from_token(raw_token)

    if not email:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = (
        db.query(User)
        .filter(func.lower(User.email) == email.lower())
        .first()
    )

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # -------------------------------
    # Exchange code → access token
    # -------------------------------
    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.get(
            f"https://graph.facebook.com/{FB_VERSION}/oauth/access_token",
            params={
                "client_id": LOGIN_APP_ID,
                "redirect_uri": LOGIN_REDIRECT_URI,
                "client_secret": LOGIN_APP_SECRET,
                "code": code,
            },
        )

        token_json = token_resp.json()
        access_token = token_json.get("access_token")

        if not access_token:
            return JSONResponse(
                {"error": "Token exchange failed", "response": token_json},
                status_code=400,
            )

        # -------------------------------
        # Fetch Facebook profile
        # -------------------------------
        me_resp = await client.get(
            f"https://graph.facebook.com/{FB_VERSION}/me",
            params={
                "fields": "id,name,email,picture.width(400).height(400)",
                "access_token": access_token,
            },
        )

        me_json = me_resp.json()

    fb_id = me_json.get("id")
    if not fb_id:
        raise HTTPException(status_code=400, detail="Invalid Facebook profile")

    picture_url = (
        me_json.get("picture", {})
        .get("data", {})
        .get("url")
    )

    # -------------------------------
    # Link Facebook account
    # -------------------------------
    existing = (
        db.query(FacebookUser)
        .filter(FacebookUser.fb_user_id == fb_id)
        .first()
    )

    if existing:
        if existing.user_id != user.id:
            raise HTTPException(
                status_code=409,
                detail="Facebook already linked to another user",
            )

        existing.name = me_json.get("name")
        existing.email = me_json.get("email")
        existing.picture_url = picture_url
        existing.access_token = access_token

    else:
        fb_user = FacebookUser(
            user_id=user.id,
            fb_user_id=fb_id,
            name=me_json.get("name"),
            email=me_json.get("email"),
            picture_url=picture_url,
            access_token=access_token,
        )
        db.add(fb_user)

    db.commit()

    # -------------------------------
    # Redirect to frontend
    # -------------------------------
    return RedirectResponse(
        url=f"{FRONTEND_SUCCESS_URL}?status=true&provider=facebook",
        status_code=status.HTTP_302_FOUND,
    )

# ---------- BIND PAGE ----------
from src.routers.social_media.schemas.facebook_schemas import FacebookPageBindRequest
@router.post("/bind-page")
def bind_facebook_page(
    payload: FacebookPageBindRequest,
    db: Session = Depends(get_db),
):
    """
    Bind a Facebook Page ID to an existing Facebook User
    """

    # 1️ Decode token (handle URL-encoded case)
    try:
        decoded_token = unquote(payload.token)
        token_data = json.loads(decoded_token)
        fb_user_id = token_data.get("user_facebook_id")
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid token format"
        )

    if not fb_user_id:
        raise HTTPException(
            status_code=400,
            detail="user_facebook_id missing in token"
        )

    # 2️ Find user
    user = (
        db.query(FacebookUser)
        .filter(FacebookUser.fb_user_id == fb_user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Facebook user not found"
        )

    # 3️ Save page ID
    user.fb_page_id = payload.fb_page_id
    db.commit()
    db.refresh(user)

    # 4️ Response
    return {
        "status": True,
        "message": "Facebook page linked successfully",
        "fb_user_id": fb_user_id,
        "fb_page_id": payload.fb_page_id,
    }

@router.get("/user/{fb_id}")
async def get_facebook_user(
    fb_id: str,
    db: Session = Depends(get_db)
):
    user = db.query(FacebookUser).filter(FacebookUser.fb_user_id == fb_id).first()

    if not user:
        return {"error": "User not found"}

    return {
        "fb_id": user.fb_user_id,
        "name": user.name,
        "email": user.email,
        "picture_url": user.picture_url,
        "page_id": user.fb_page_id,
        "access_token": user.access_token,
    }
    