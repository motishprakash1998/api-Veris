import os
import requests
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from loguru import logger
from ..models import Platform, SocialAccount, AccountProfile, AccountSnapshot

# ---- CONFIG ----
SCRAPECREATORS_FB_PROFILE_URL = "https://api.scrapecreators.com/v1/facebook/profile"
SCRAPECREATORS_API_KEY = os.getenv("SCRAPECREATORS_API_KEY", "7hwQUwBBRweHD7vW7cw5hqTUXHb2")


def _first_non_empty(*vals):
    """Return the first non-empty value."""
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and v.strip():
            return v.strip()
        if v:
            return v
    return None


def fetch_facebook_profile(username_or_id: str, db):
    """
    Fetch Facebook profile using ScrapeCreators API (by passing the full URL)
    and save/update in DB.
    """

    if not username_or_id:
        raise HTTPException(status_code=400, detail="username_or_id is required")

    headers = {"x-api-key": SCRAPECREATORS_API_KEY}

    # 🔥 Important: ScrapeCreators expects full Facebook URL, not username
    # If user gives plain username or ID, we build a valid Facebook URL.
    if username_or_id.startswith("http"):
        fb_url = username_or_id
    else:
        # Remove spaces and ensure clean slug for URL
        clean_name = username_or_id.replace(" ", "")
        fb_url = f"https://www.facebook.com/{clean_name}/"

    params = {"url": fb_url}

    try:
        response = requests.get(SCRAPECREATORS_FB_PROFILE_URL, headers=headers, params=params, timeout=30)
    except requests.RequestException as e:
        logger.error(f"ScrapeCreators request error: {e}")
        raise HTTPException(status_code=502, detail="Failed to reach ScrapeCreators service")

    logger.info(f"ScrapeCreators status={response.status_code}")
    if response.status_code != 200:
        logger.error(f"ScrapeCreators error: {response.text[:500]}")
        raise HTTPException(status_code=response.status_code, detail="Failed to fetch Facebook profile")

    data = response.json()
    if not isinstance(data, dict) or not data:
        raise HTTPException(status_code=502, detail="Invalid response from ScrapeCreators API")

    # ---- Extract values from API response ----
    platform_user_id = str(data.get("id"))
    display_name = data.get("name")
    username_val = display_name  # same as display_name (as per your rule)
    profile_url = f"https://www.facebook.com/{username_val.replace(' ', '')}/"

    follower_count = data.get("followerCount")
    like_count = data.get("likeCount")

    profile_image_url = _first_non_empty(
        data.get("profilePicLarge"),
        data.get("profilePicMedium"),
        data.get("profilePicSmall"),
        (data.get("profilePhoto") or {}).get("url")
    )

    bio = data.get("pageIntro")
    category = data.get("category")
    creation_date = data.get("creationDate")
    is_verified = bool(data.get("isBusinessPageActive", False))
    is_private = False

    # ---- Upsert Platform('facebook') ----
    platform = db.query(Platform).filter_by(code="facebook").first()
    if not platform:
        platform = Platform(code="facebook", display_name="Facebook")
        db.add(platform)
        db.commit()
        db.refresh(platform)

    # ---- Upsert SocialAccount ----
    account = db.query(SocialAccount).filter_by(
        platform_id=platform.id,
        platform_user_id=platform_user_id,
    ).first()

    if not account:
        account = SocialAccount(
            platform_id=platform.id,
            platform_user_id=platform_user_id,
            username=username_val,
            profile_url=profile_url,
            is_verified=is_verified,
            is_private=is_private,
            last_seen_at=datetime.utcnow(),
        )
        db.add(account)
    else:
        account.username = username_val
        account.profile_url = profile_url
        account.is_verified = is_verified
        account.is_private = is_private
        account.last_seen_at = datetime.utcnow()

    db.commit()
    db.refresh(account)

    # ---- AccountProfile ----
    profile = AccountProfile(
        social_account_id=account.id,
        display_name=display_name,
        bio=bio,
        follower_count=follower_count,
        following_count=None,
        post_count=None,
        profile_image_url=profile_image_url,
        is_private=is_private,
        like_count=like_count,
        source="scrapecreators",
        # category=category,
    )
    db.add(profile)

    # ---- AccountSnapshot ----
    snapshot = AccountSnapshot(
        social_account_id=account.id,
        follower_count=follower_count,
        following_count=None,
        post_count=None,
        # like_count=like_count,
    )
    db.add(snapshot)

    try:
        db.commit()
    except IntegrityError as e:
        logger.warning(f"IntegrityError on FB profile upsert: {e}")
        db.rollback()

    return {
        "id": account.id,
        "platform_user_id": platform_user_id,
        "username": username_val,
        "display_name": display_name,
        "bio": bio,
        "likes": like_count,
        "followers": follower_count,
        "profile_pic": profile_image_url,
        "is_verified": is_verified,
        "is_private": is_private,
        "profile_url": profile_url,
        "category": category,
        "creation_date": creation_date,
        "source": "scrapecreators",
    }
