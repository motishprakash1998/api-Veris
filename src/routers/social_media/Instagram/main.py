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
