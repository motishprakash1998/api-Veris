import requests
from loguru import logger
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from sqlalchemy.exc import IntegrityError
from ..models import (Platform, 
                      SocialAccount, 
                      AccountProfile, 
                      AccountSnapshot, 
                      Post, 
                      PostMetric, 
                      Engagement)

# NOTE: The RapidAPI key is currently hard-coded for the user's example.
RAPIDAPI_HOST = "instagram-scraper-20251.p.rapidapi.com"
RAPIDAPI_KEY = "824d406ef9msha142b14f2e8c048p107c91jsnf1b131b9ca6a"


HEADERS = {
    "x-rapidapi-host": RAPIDAPI_HOST,
    "x-rapidapi-key": RAPIDAPI_KEY,
}
# --------------------------------------------------
# 🔹 CHANGE DETECTION HELPERS
# --------------------------------------------------

def profile_has_changed(user: dict, last_profile) -> bool:
    if not last_profile:
        return True

    return any([
        last_profile.display_name != user.get("full_name"),
        last_profile.bio != user.get("biography"),
        last_profile.profile_image_url != (
            user.get("profile_pic_url_hd") or user.get("profile_pic_url")
        ),
        last_profile.is_private != user.get("is_private"),
    ])


def snapshot_has_changed(user: dict, last_snapshot) -> bool:
    if not last_snapshot:
        return True

    return any([
        last_snapshot.follower_count != user.get("follower_count"),
        last_snapshot.following_count != user.get("following_count"),
        last_snapshot.post_count != user.get("media_count"),
    ])


# --------------------------------------------------
# 🔹 MAIN FUNCTION
# --------------------------------------------------
def fetch_instagram_profile(username: str, db: Session):
    """
    Fetch Instagram profile from RapidAPI.
    - social_accounts  → latest state
    - account_profiles → profile change history
    - account_snapshots → growth timeline
    """

    # --------------------------------------------------
    # 1️⃣ Fetch from RapidAPI
    # --------------------------------------------------
    url = f"https://{RAPIDAPI_HOST}/userinfo/"
    params = {"username_or_id": username}

    try:
        resp = requests.get(
            url, headers=HEADERS, params=params, timeout=15
        )
    except requests.RequestException:
        logger.exception("Instagram API call failed")
        raise HTTPException(status_code=502, detail="Instagram API failed")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Instagram API error: {resp.text}",
        )

    payload = resp.json()
    if not payload or "data" not in payload:
        raise HTTPException(status_code=400, detail="Invalid Instagram response")

    user = payload["data"]

    ig_user_id = str(user.get("id") or user.get("instagram_pk"))
    ig_username = user.get("username")

    if not ig_user_id or not ig_username:
        raise HTTPException(status_code=400, detail="Invalid Instagram data")

    # --------------------------------------------------
    # 2️⃣ Ensure platform exists
    # --------------------------------------------------
    platform = db.query(Platform).filter_by(code="instagram").first()
    if not platform:
        platform = Platform(code="instagram", display_name="Instagram")
        db.add(platform)
        db.commit()
        db.refresh(platform)

    # --------------------------------------------------
    # 3️⃣ UPSERT social_accounts (LATEST STATE)
    # --------------------------------------------------
    account = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.platform_id == platform.id,
            (
                (SocialAccount.platform_user_id == ig_user_id)
                | (SocialAccount.username == ig_username)
            )
        )
        .first()
    )

    if not account:
        account = SocialAccount(
            platform_id=platform.id,
            platform_user_id=ig_user_id,
            username=ig_username,
            profile_url=f"https://instagram.com/{ig_username}",
            is_verified=user.get("is_verified", False),
            is_private=user.get("is_private", False),
            last_seen_at=datetime.utcnow(),
        )
        db.add(account)
    else:
        account.platform_user_id = ig_user_id
        account.username = ig_username
        account.is_verified = user.get("is_verified", False)
        account.is_private = user.get("is_private", False)
        account.last_seen_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(account)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Instagram account conflict")

    # --------------------------------------------------
    # 4️⃣ GET LAST PROFILE + SNAPSHOT
    # --------------------------------------------------
    last_profile = (
        db.query(AccountProfile)
        .filter_by(social_account_id=account.id)
        .order_by(AccountProfile.created_at.desc())
        .first()
    )

    last_snapshot = (
        db.query(AccountSnapshot)
        .filter_by(social_account_id=account.id)
        .order_by(AccountSnapshot.created_at.desc())
        .first()
    )

    # --------------------------------------------------
    # 5️⃣ PROFILE HISTORY (ONLY IF CHANGED)
    # --------------------------------------------------
    if profile_has_changed(user, last_profile):
        db.add(AccountProfile(
            social_account_id=account.id,
            display_name=user.get("full_name"),
            bio=user.get("biography"),
            profile_image_url=user.get("profile_pic_url_hd")
            or user.get("profile_pic_url"),
            is_private=user.get("is_private"),
            follower_count=user.get("follower_count"),
            following_count=user.get("following_count"),
            post_count=user.get("media_count"),
            source="api",
        ))

    # --------------------------------------------------
    # 6️⃣ SNAPSHOT HISTORY (ONLY IF CHANGED)
    # --------------------------------------------------
    if snapshot_has_changed(user, last_snapshot):
        db.add(AccountSnapshot(
            social_account_id=account.id,
            follower_count=user.get("follower_count"),
            following_count=user.get("following_count"),
            post_count=user.get("media_count"),
        ))

    # --------------------------------------------------
    # 7️⃣ FINAL COMMIT
    # --------------------------------------------------
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.warning("Duplicate profile/snapshot skipped")

    # --------------------------------------------------
    # 8️⃣ RESPONSE
    # --------------------------------------------------
    return {
        "id": account.id,
        "platform": "instagram",
        "username": ig_username,
        "full_name": user.get("full_name"),
        "followers": user.get("follower_count"),
        "following": user.get("following_count"),
        "posts": user.get("media_count"),
        "is_verified": user.get("is_verified"),
        "is_private": user.get("is_private"),
        "profile_pic": user.get("profile_pic_url_hd")
        or user.get("profile_pic_url"),
        "profile_url": f"https://instagram.com/{ig_username}",
        "synced_at": datetime.utcnow(),
    }


def fetch_instagram_posts(username: str, db: Session):
    """
    Fetch Instagram posts intelligently:
    - If post count unchanged → skip
    - If increased → save only new posts
    """

    # --------------------------------------------------
    # 1️⃣ Find social account
    # --------------------------------------------------
    account = (
        db.query(SocialAccount)
        .filter(SocialAccount.username == username)
        .first()
    )

    if not account:
        raise HTTPException(status_code=404, detail="Instagram account not found")

    # --------------------------------------------------
    # 2️⃣ Get last saved post
    # --------------------------------------------------
    last_post = (
        db.query(Post)
        .filter(Post.social_account_id == account.id)
        .order_by(Post.created_at.desc())
        .first()
    )

    last_post_time = last_post.created_at if last_post else None

    # --------------------------------------------------
    # 3️⃣ Call API (once)
    # --------------------------------------------------
    url = f"https://{RAPIDAPI_HOST}/userposts/{username}"

    r = requests.get(url, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Instagram posts API failed")

    items = r.json().get("items", [])
    if not items:
        return []

    results = []

    # --------------------------------------------------
    # 4️⃣ Iterate ONLY NEW POSTS
    # --------------------------------------------------
    for item in items:
        post_time = datetime.fromtimestamp(item["taken_at"])

        # 🛑 stop when we reach already saved posts
        if last_post_time and post_time <= last_post_time:
            break

        # --------------------------------------------------
        # Create post if not exists
        # --------------------------------------------------
        post = (
            db.query(Post)
            .filter_by(
                social_account_id=account.id,
                platform_post_id=item["id"],
            )
            .first()
        )

        if not post:
            post = Post(
                social_account_id=account.id,
                platform_post_id=item["id"],
                created_at=post_time,
                text=item.get("caption", {}).get("text"),
                language="en",
            )
            db.add(post)
            db.flush()  # ⚡ no commit yet

        # --------------------------------------------------
        # Always store metrics snapshot
        # --------------------------------------------------
        metric = PostMetric(
            post_id=post.id,
            like_count=item.get("like_count"),
            comment_count=item.get("comment_count"),
            view_count=item.get("view_count"),
        )
        db.add(metric)

        results.append({
            "post_id": item["id"],
            "likes": metric.like_count,
            "comments": metric.comment_count,
            "views": metric.view_count,
        })

    # --------------------------------------------------
    # 5️⃣ Final commit
    # --------------------------------------------------
    db.commit()

    return results
