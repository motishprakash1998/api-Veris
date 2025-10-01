import requests
from typing import Dict, Any, Optional
import requests
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from datetime import datetime
from ..models import Platform, SocialAccount, AccountProfile, AccountSnapshot, Post, PostMetric, Engagement
# NOTE: The RapidAPI key is currently hard-coded for the user's example.
# It's strongly recommended to move this to environment variables or config.
RAPIDAPI_HOST = "instagram-scraper-20251.p.rapidapi.com"
# RAPIDAPI_URL = f"https://{RAPIDAPI_HOST}/userinfo/"
RAPIDAPI_KEY = "824d406ef9msha142b14f2e8c048p107c91jsnf1b131b9ca6a"

from loguru import logger
# def fetch_instagram_profile(username: str) -> Dict[str, Any]:
#     """Fetch profile info from RapidAPI Instagram scraper and return selected fields.

#     Returns a dict with keys requested by the user or raises an exception on error.
#     """
#     if not username:
#         raise ValueError("username is required")

#     headers = {
#         "x-rapidapi-key": RAPIDAPI_KEY,
#         "x-rapidapi-host": RAPIDAPI_HOST,
#     }
#     params = {"username_or_id": username}

#     resp = requests.get(RAPIDAPI_URL, headers=headers, params=params, timeout=10)
#     resp.raise_for_status()
#     response_dict = resp.json()

#     data = response_dict.get("data", {}) or {}

#     profile_info = {
#         "full_name": data.get("full_name"),
#         "username": data.get("username"),
#         "followers": data.get("follower_count"),
#         "following": data.get("following_count"),
#         "media_count": data.get("media_count"),
#         "is_private": data.get("is_private"),
#         "bio": data.get("biography"),
#         "hashtags": [
#             e["hashtag"]["name"]
#             for e in data.get("biography_with_entities", {}).get("entities", [])
#             if "hashtag" in e
#         ],
#         "profile_pic_url": data.get("hd_profile_pic_url_info", {}).get("url"),
#         "category": data.get("category"),
#         "is_verified": data.get("is_verified"),
#         "external_url": data.get("external_url"),
#     }

#     return profile_info


HEADERS = {
    "x-rapidapi-host": RAPIDAPI_HOST,
    "x-rapidapi-key": RAPIDAPI_KEY,
}
def fetch_instagram_profile(username: str, db: Session):
    """Fetch Instagram profile from RapidAPI and save to DB."""
    url = f"https://{RAPIDAPI_HOST}/userinfo/"
    params = {"username_or_id": username}
    r = requests.get(url, headers=HEADERS, params=params)
    logger.error(f"Instagram API response: {r} {r.status_code} - {r.text}")

    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail="Failed to fetch profile")

    data = r.json()
    if not data or "data" not in data:
        raise ValueError("Invalid profile response")

    user = data["data"]

    # Ensure Instagram platform exists
    platform = db.query(Platform).filter_by(code="instagram").first()
    if not platform:
        platform = Platform(code="instagram", display_name="Instagram")
        db.add(platform)
        db.commit()
        db.refresh(platform)

    # Upsert social account
    account = db.query(SocialAccount).filter_by(
        platform_id=platform.id, platform_user_id=str(user.get("id") or user.get("instagram_pk"))
    ).first()

    if not account:
        account = SocialAccount(
            platform_id=platform.id,
            platform_user_id=str(user.get("id") or user.get("instagram_pk")),
            username=user.get("username"),
            profile_url=f"https://instagram.com/{user.get('username')}",
            is_verified=user.get("is_verified"),
            is_private=user.get("is_private"),
            last_seen_at=datetime.utcnow(),
        )
        db.add(account)
    else:
        account.username = user.get("username")
        account.is_verified = user.get("is_verified")
        account.is_private = user.get("is_private")
        account.last_seen_at = datetime.utcnow()

    db.commit()
    db.refresh(account)

    # Save latest profile snapshot
    profile = AccountProfile(
        social_account_id=account.id,
        display_name=user.get("full_name"),
        bio=user.get("biography"),
        follower_count=user.get("follower_count"),
        following_count=user.get("following_count"),
        post_count=user.get("media_count"),
        profile_image_url=user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
        is_private=user.get("is_private"),
        source="api",
    )
    db.add(profile)

    snapshot = AccountSnapshot(
        social_account_id=account.id,
        follower_count=user.get("follower_count"),
        following_count=user.get("following_count"),
        post_count=user.get("media_count"),
    )
    db.add(snapshot)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()

    return {
        "id": account.id,
        "username": account.username,
        "full_name": user.get("full_name"),
        "followers": user.get("follower_count"),
        "following": user.get("following_count"),
        "posts": user.get("media_count"),
        "profile_pic": user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
        "bio": user.get("biography"),
    }


def fetch_instagram_posts(username: str, db: Session):
    """Fetch user posts and save to DB."""
    url = f"https://{RAPIDAPI_HOST}/userposts/{username}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        return []

    posts_data = r.json().get("items", [])
    results = []

    # Find the account
    account = db.query(SocialAccount).filter(SocialAccount.username == username).first()
    if not account:
        return []

    for item in posts_data:
        post = db.query(Post).filter_by(
            social_account_id=account.id, platform_post_id=item["id"]
        ).first()

        if not post:
            post = Post(
                social_account_id=account.id,
                platform_post_id=item["id"],
                created_at=datetime.fromtimestamp(item["taken_at"]),
                text=item.get("caption", {}).get("text"),
                language="en",
            )
            db.add(post)
            db.commit()
            db.refresh(post)

        metric = PostMetric(
            post_id=post.id,
            like_count=item.get("like_count"),
            comment_count=item.get("comment_count"),
            view_count=item.get("view_count"),
        )
        db.add(metric)
        results.append({
            "post_id": post.platform_post_id,
            "likes": metric.like_count,
            "comments": metric.comment_count,
            "views": metric.view_count,
        })

    db.commit()
    return results
