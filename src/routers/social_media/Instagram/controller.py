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
                      PostMedia,
                      Engagement)

# NOTE: The RapidAPI key is currently hard-coded for the user's example.
RAPIDAPI_HOST = "instagram-scraper-20251.p.rapidapi.com"
# RAPIDAPI_KEY = "824d406ef9msha142b14f2e8c048p107c91jsnf1b131b9ca6a"
RAPIDAPI_KEY = "3ce8c354e3msh22662032620dd62p121c70jsn15208e443454"

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
    url = f"https://{RAPIDAPI_HOST}/userinfo"
    params = {
        "username_or_id": username
    }
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

from datetime import datetime
import requests

def _extract_media_from_item(item: dict):
    """
    Returns list of media dicts:
    [
      {"media_type": "image", "media_url": "...", "media_metadata": {...}},
      ...
    ]
    """
    media_list = []

    # ✅ Case 1: carousel
    carousel = item.get("carousel_media") or []
    if carousel:
        for m in carousel:
            media_type = "image"
            media_url = None

            # video
            if m.get("video_versions"):
                media_type = "video"
                media_url = m["video_versions"][0].get("url")

            # image
            elif m.get("image_versions2", {}).get("candidates"):
                media_type = "image"
                media_url = m["image_versions2"]["candidates"][0].get("url")

            if media_url:
                media_list.append({
                    "media_type": media_type,
                    "media_url": media_url,
                    "media_metadata": {
                        "id": m.get("id"),
                        "is_video": m.get("is_video"),
                    }
                })

        return media_list

    # ✅ Case 2: single video
    if item.get("video_versions"):
        media_url = item["video_versions"][0].get("url")
        if media_url:
            media_list.append({
                "media_type": "video",
                "media_url": media_url,
                "media_metadata": {
                    "id": item.get("id"),
                    "is_video": item.get("is_video"),
                }
            })
        return media_list

    # ✅ Case 3: single image
    candidates = item.get("image_versions2", {}).get("candidates", [])
    if candidates:
        media_url = candidates[0].get("url")
        if media_url:
            media_list.append({
                "media_type": "image",
                "media_url": media_url,
                "media_metadata": {
                    "id": item.get("id"),
                    "is_video": item.get("is_video"),
                }
            })

    return media_list


def fetch_instagram_posts(username: str, db: Session, max_posts: int = 20, cursor: str | None = None):
    """
    ✅ Saves:
    - Post -> posts
    - PostMetric -> post_metrics
    - PostMedia -> post_media
    ✅ Returns:
    - results list
    - next_cursor for "next button"
    """

    try:
        logger.info(f"🚀 [IG POSTS] Start | username='{username}' | max_posts={max_posts} | cursor={cursor}")

        # 1) Find account
        account = db.query(SocialAccount).filter(SocialAccount.username == username).first()
        if not account:
            logger.warning(f"⚠️ [IG POSTS] SocialAccount not found: {username}")
            return {"items": [], "next_cursor": None}

        # 2) last saved post
        last_post = (
            db.query(Post)
            .filter(Post.social_account_id == account.id)
            .order_by(Post.created_at.desc())
            .first()
        )
        last_post_time = last_post.created_at if last_post else None
        logger.info(f"🕒 [IG POSTS] last_post_time={last_post_time}")

        # 3) API call
        url = f"https://{RAPIDAPI_HOST}/userposts"
        params = {"username_or_id": username}

        # ✅ Pagination (depends on API, common params)
        if cursor:
            params["max_id"] = cursor  # some APIs use max_id / next_max_id / end_cursor

        logger.info(f"🌐 [IG POSTS] Calling API | url={url} | params={params}")

        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)

        logger.info(f"📡 [IG POSTS] status={resp.status_code} | url={resp.url}")
        logger.debug(f"📦 [IG POSTS] raw={resp.text[:500]}")

        if resp.status_code != 200:
            logger.error(f"❌ [IG POSTS] API failed: {resp.status_code} | {resp.text[:200]}")
            return {"items": [], "next_cursor": None}

        payload = resp.json()
        data = payload.get("data") or payload
        items = data.get("items", [])

        # ✅ next cursor (API dependent)
        next_cursor = (
            data.get("next_max_id")
            or data.get("next_id")
            or data.get("end_cursor")
            or None
        )

        logger.info(f"📌 [IG POSTS] items_received={len(items)} | next_cursor={next_cursor}")

        results = []
        inserted_posts = 0
        inserted_metrics = 0
        inserted_media = 0

        # 4) iterate posts (limit max_posts)
        for item in items[:max_posts]:
            if "taken_at" not in item or "id" not in item:
                continue
            
            from datetime import timezone
            post_time = datetime.fromtimestamp(item["taken_at"], tz=timezone.utc)
            platform_post_id = str(item["id"])

            # optional stop when old posts reached
            if last_post_time and post_time <= last_post_time:
                logger.info(f"🛑 [IG POSTS] stop old post reached | {post_time} <= {last_post_time}")
                break

            # create post
            post = (
                db.query(Post)
                .filter_by(social_account_id=account.id, platform_post_id=platform_post_id)
                .first()
            )

            if not post:
                post = Post(
                    social_account_id=account.id,
                    platform_post_id=platform_post_id,
                    created_at=post_time,
                    text=item.get("caption", {}).get("text"),
                    language="en",
                    raw_response=item,   # ✅ store raw item
                )
                db.add(post)
                db.flush()
                inserted_posts += 1
                logger.info(f"✅ [IG POSTS] Post inserted | post_id={post.id} | platform_post_id={platform_post_id}")

            # ✅ insert metric snapshot
            metric = PostMetric(
                post_id=post.id,
                like_count=item.get("like_count"),
                comment_count=item.get("comment_count"),
                view_count=item.get("view_count"),
                share_count=item.get("reshare_count") or item.get("share_count"),
                extra={
                    "has_liked": item.get("has_liked"),
                    "play_count": item.get("play_count"),
                },
            )
            db.add(metric)
            inserted_metrics += 1

            # ✅ insert media
            media_list = _extract_media_from_item(item)
            for m in media_list:
                media = PostMedia(
                    post_id=post.id,
                    media_type=m.get("media_type"),
                    media_url=m.get("media_url"),
                    media_metadata=m.get("media_metadata"),
                )
                db.add(media)
                inserted_media += 1

            results.append({
                "post_id": platform_post_id,
                "db_post_id": post.id,
                "created_at": post_time.isoformat(),
                "likes": item.get("like_count"),
                "comments": item.get("comment_count"),
                "views": item.get("view_count"),
                "media_count": len(media_list),
            })

        # 5) Commit
        logger.info(
            f"💾 [IG POSTS] committing... inserted_posts={inserted_posts} "
            f"inserted_metrics={inserted_metrics} inserted_media={inserted_media}"
        )

        db.commit()

        logger.info("🎉 [IG POSTS] commit success ✅")

        return {
            "items": results,
            "next_cursor": next_cursor
        }

    except IntegrityError as ie:
        db.rollback()
        logger.exception(f"❌ [IG POSTS] IntegrityError: {ie}")
        return {"items": [], "next_cursor": None}

    except Exception as e:
        db.rollback()
        logger.exception(f"🔥 [IG POSTS] Unexpected error: {e}")
        return {"items": [], "next_cursor": None}