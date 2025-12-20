import os
import re
import requests
from . import controller
from typing import Optional,List
from src.database import get_db
from urllib.parse import urlparse,parse_qs, quote
from sqlalchemy.orm import Session
from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks,Request, status
from fastapi.responses import RedirectResponse, JSONResponse
from dotenv import load_dotenv

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
APP_ID = os.getenv("FB_APP_ID", "2007595690062087")
APP_SECRET = os.getenv("FB_APP_SECRET", "61175cf6e37f68bf12d1ea59749e9fe9")
ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN", f"{APP_ID}|{APP_SECRET}")

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
    Accepts both:
    - Plain name:  LalchandKatariaOfficial
    - Full URL:    https://www.facebook.com/LalchandKatariaOfficial/
    """
    page_name = extract_page_name(input_value)
    page_data = fetch_page_basic(page_name)

    return JSONResponse(
        content={
            "id": page_data["id"],
            "name": page_data.get("name", ""),
            "about": page_data.get("about"),
            "category": page_data.get("category"),
            "link": page_data.get("link"),
            "fan_count": page_data.get("fan_count"),
            "followers_count": page_data.get("followers_count"),
            "picture_url": page_data.get("profile_picture"),
        }
    )
# --- Helpers ---

# --- Endpoint ---

@router.get("/page/posts")
def get_page_posts(
    input_value: str = Query(..., description="Facebook Page name or full URL"),
    after: Optional[str] = Query(None, description="Pagination cursor for next page"),
    before: Optional[str] = Query(None, description="Pagination cursor for previous page"),
    limit: int = Query(10, description="Number of posts per page (default 10)"),
    db: Session = Depends(get_db),
):
    """
    Fetch Facebook page info and recent posts.
    Supports pagination via 'after' and 'before' cursors.
    """
    page_name = extract_page_name(input_value)
    page_basic = fetch_page_basic(page_name)

    if page_basic.get("error"):
        raise HTTPException(status_code=400, detail=page_basic["error"]["message"])

    page_id = page_basic.get("id")
    if not page_id:
        raise HTTPException(status_code=404, detail="Could not determine Page ID")

    # Fetch posts with correct pagination handling
    posts_res = fetch_posts_for_page(page_id, after_cursor=after, before_cursor=before, limit=limit)

    if posts_res.get("error"):
        raise HTTPException(status_code=400, detail=posts_res["error"]["message"])

    raw_posts = posts_res.get("data", [])
    posts = [normalize_post(p) for p in raw_posts]

    paging = posts_res.get("paging", {})
    cursors = paging.get("cursors", {}) if paging else {}
    next_cursor = cursors.get("after")
    prev_cursor = cursors.get("before")

    return JSONResponse(
        content={
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
        }
    )
    

# ====== CONFIG (change these or set env vars) ======
LOGIN_APP_ID = os.environ.get("FB_APP_ID", "2037441327057334")
LOGIN_APP_SECRET = os.environ.get("FB_APP_SECRET", "f6579b31b6f6186aecda29b5be8a4481")
# Make sure this matches exactly the URI registered in Facebook App settings
LOGIN_REDIRECT_URI = os.environ.get("FB_REDIRECT_URI", "https://backend-veris.skyserver.net.in/api/facebook/callback")
FB_VERSION = os.environ.get("FB_VERSION", "v16.0")

REQUIRED_SCOPE = ["email", "public_profile"]
OPTIONAL_SCOPES = {
    "user_link": "Access user profile URL (link)",
    "user_posts": "Read user timeline posts (user_posts)",
    "user_photos": "Read user photos (user_photos)",
    "user_location": "Access user location (user_location)",
}


def _ensure_session(request: Request) -> None:
    if getattr(request, "session", None) is None:
        raise RuntimeError(
            "Session middleware not configured. Add SessionMiddleware to your FastAPI app:\n"
            "app.add_middleware(SessionMiddleware, secret_key=...)"
        )




JWT_SECRET = "CHANGE_THIS_SECRET"
JWT_ALGO = "HS256"

REQUIRED_SCOPE = ["public_profile"]
OPTIONAL_SCOPES = {
    "email",
    "user_posts",
    "user_photos",
    "user_location",
    "user_link",
}

FRONTEND_SUCCESS_URL = "https://voxstrategix.com/auth/success"

import httpx
from src.routers.social_media.models.facebook_models import FacebookUser
import jwt

@router.get("/login")
async def facebook_login(request: Request) -> RedirectResponse:
    raw_qs = urlparse(str(request.url)).query
    parsed = parse_qs(raw_qs)
    chosen: List[str] = parsed.get("scopes", [])

    scopes = list(REQUIRED_SCOPE)
    for c in chosen:
        if c in OPTIONAL_SCOPES and c not in scopes:
            scopes.append(c)

    scope_str = ",".join(scopes)

    auth_url = (
        f"https://www.facebook.com/{FB_VERSION}/dialog/oauth?"
        f"client_id={LOGIN_APP_ID}"
        f"&redirect_uri={quote(LOGIN_REDIRECT_URI)}"
        f"&scope={quote(scope_str)}"
        f"&response_type=code"
    )

    request.session["requested_scopes"] = scopes

    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)

# ---------- CALLBACK ----------
@router.get("/callback")
async def facebook_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    qs = request.query_params

    if "error" in qs:
        return JSONResponse({"error": dict(qs)}, status_code=400)

    code = qs.get("code")
    if not code:
        return JSONResponse({"error": "Missing code"}, status_code=400)

    async with httpx.AsyncClient(timeout=10) as client:

        # ---- TOKEN ----
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

        # ---- PERMISSIONS ----
        perms_resp = await client.get(
            f"https://graph.facebook.com/{FB_VERSION}/me/permissions",
            params={"access_token": access_token},
        )

        perms_json = perms_resp.json()
        granted = [
            p["permission"]
            for p in perms_json.get("data", [])
            if p.get("status") == "granted"
        ]

        # ---- PROFILE ----
        fields = ["id", "name", "picture.width(400).height(400)"]
        if "email" in granted:
            fields.append("email")
        if "user_location" in granted:
            fields.append("location")
        if "user_link" in granted:
            fields.append("link")

        fields_str = ",".join(fields)

        me_resp = await client.get(
            f"https://graph.facebook.com/{FB_VERSION}/me",
            params={"fields": fields_str, "access_token": access_token},
        )

        me_json = me_resp.json()

    fb_id = me_json.get("id")
    if not fb_id:
        return JSONResponse({"error": "Invalid Facebook profile"}, status_code=400)

    picture_url = None
    if me_json.get("picture", {}).get("data"):
        picture_url = me_json["picture"]["data"].get("url")

    existing = (
        db.query(FacebookUser)
        .filter(FacebookUser.fb_user_id == fb_id)
        .first()
    )

    if existing:
        existing.name = me_json.get("name")
        existing.email = me_json.get("email")
        existing.picture_url = picture_url
    else:
        existing = FacebookUser(
            fb_user_id=fb_id,
            name=me_json.get("name"),
            email=me_json.get("email"),
            picture_url=picture_url,
        )
        db.add(existing)

    db.commit()
    db.refresh(existing)

    # ---- JWT ----
    import json
    from urllib.parse import quote

    payload = json.dumps({"user_facebook_id": fb_id})
    token = quote(payload)


    return RedirectResponse(
        url=f"{FRONTEND_SUCCESS_URL}?status=true&token={token}",
        status_code=302,
    )


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
    

@router.get("/save_page/info")
def get_page_info(
    input_value: str = Query(..., description="Facebook Page name or full URL"),
    db: Session = Depends(get_db),
):
    """
    🔹 Get basic information about a Facebook Page.
    Accepts both:
    - Plain name:  LalchandKatariaOfficial
    - Full URL:    https://www.facebook.com/LalchandKatariaOfficial/
    """
    

    return None
    