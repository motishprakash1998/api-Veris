import requests
from . import controller
from sqlalchemy import func 
from src.database import get_db
from sqlalchemy.orm import Session
from src.utils.jwt import get_email_from_token
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from src.routers.user_management.models.users import User
from fastapi.responses import RedirectResponse, JSONResponse
from src.routers.social_media.models.ig_models import InstagramUser
from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks, Request

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

import re
def extract_instagram_username(value: str) -> str:
    value = value.strip()

    # Full profile URL
    match = re.search(r"instagram\.com/([^/?#]+)/?", value)
    if match:
        return match.group(1)

    # Plain username
    return value

@router.get("/post-validate", summary="Validate Instagram username and return profile info")
def postvalidate(
    username: str = Query(..., description="Instagram username to lookup"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """Fetch Instagram profile and schedule background fetch for posts/metrics."""
    try:
        profile = controller.fetch_instagram_posts(username, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except requests.exceptions.RequestException as re:
        raise HTTPException(status_code=502, detail=str(re))

    # # Kick off background job to fetch posts
    # background_tasks.add_task(controller.fetch_instagram_posts, username, db)

    response = {
        "success": True,
        "status": 200,
        "message": f"Fetched profile data for {username} successfully.",
        "data": profile,
    }
    return response


@router.post("/bind-page", summary="Bind Instagram username to current user")
def save_instagram_username(
    payload: dict,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
):
    email = get_email_from_token(token)
    if not email:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = (
        db.query(User)
        .filter(func.lower(User.email) == email.lower())
        .first()
    )

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    raw_value = payload.get("username")

    if not raw_value:
        raise HTTPException(status_code=400, detail="username or profile link required")

    username = extract_instagram_username(raw_value)
    profile_url = f"https://www.instagram.com/{username}/"

    record = (
        db.query(InstagramUser)
        .filter(InstagramUser.user_id == user.id)
        .first()
    )

    if record:
        record.username = username
        record.profile_url = profile_url
    else:
        record = InstagramUser(
            user_id=user.id,
            username=username,
            profile_url=profile_url,
        )
        db.add(record)

    db.commit()
    db.refresh(record)

    return {
        "status": True,
        "username": record.username,
        "profile_url": record.profile_url,
    }

from ..models import (Platform, 
                      SocialAccount, 
                      AccountProfile, 
                      AccountSnapshot, 
                      Post, 
                      PostMetric, 
                      PostMedia,
                      Engagement)
from sqlalchemy.orm import joinedload
from sqlalchemy import desc
from datetime import timezone


RAPIDAPI_HOST = "instagram-scraper-20251.p.rapidapi.com"
RAPIDAPI_KEY = "3ce8c354e3msh22662032620dd62p121c70jsn15208e443454"

HEADERS = {
    "X-RapidAPI-Host": RAPIDAPI_HOST,
    "X-RapidAPI-Key": RAPIDAPI_KEY,
}

@router.get("/posts-rapid-live", summary="Get Instagram posts directly from RapidAPI (no DB)")
def get_posts_rapid_live(
    username: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
):
    """
    ✅ Direct RapidAPI → frontend
    """

    url = f"https://{RAPIDAPI_HOST}/userposts"
    params = {
        "username_or_id": username
    }

    resp = requests.get(url, headers=HEADERS, params=params, timeout=20)

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"RapidAPI failed: {resp.text}"
        )

    payload = resp.json()
    data = payload.get("data") or payload
    items = data.get("items", [])

    # limit posts
    items = items[:limit]

    # OPTIONAL: normalize minimal fields only (else return as-is)
    formatted_items = []

    for item in items:
        formatted_items.append({
            "id": item.get("id"),
            "code": item.get("code"),
            "taken_at": item.get("taken_at"),
            "caption": item.get("caption"),
            "like_count": item.get("like_count"),
            "comment_count": item.get("comment_count"),
            "view_count": item.get("view_count"),
            "media_type": item.get("media_type"),

            # ✅ media (Rapid original)
            "image_versions2": item.get("image_versions2"),
            "video_versions": item.get("video_versions"),
            "carousel_media": item.get("carousel_media"),

            # ✅ flags
            "is_video": item.get("is_video"),
            "can_save": item.get("can_save"),
            "can_reshare": item.get("can_reshare"),

            # ✅ direct IG link (if code present)
            "permalink": (
                f"https://www.instagram.com/p/{item.get('code')}/"
                if item.get("code") else None
            ),
        })

    return {
        "success": True,
        "source": "rapidapi-live",
        "username": username,
        "count": len(formatted_items),
        "items": formatted_items,
    }