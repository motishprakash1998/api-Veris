import requests
from typing import Dict, Any, Optional

# NOTE: The RapidAPI key is currently hard-coded for the user's example.
# It's strongly recommended to move this to environment variables or config.
RAPIDAPI_HOST = "instagram-scraper-20251.p.rapidapi.com"
RAPIDAPI_URL = f"https://{RAPIDAPI_HOST}/userinfo/"
RAPIDAPI_KEY = "824d406ef9msha142b14f2e8c048p107c91jsnf1b131b9ca6a"


def fetch_instagram_profile(username: str) -> Dict[str, Any]:
    """Fetch profile info from RapidAPI Instagram scraper and return selected fields.

    Returns a dict with keys requested by the user or raises an exception on error.
    """
    if not username:
        raise ValueError("username is required")

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST,
    }
    params = {"username_or_id": username}

    resp = requests.get(RAPIDAPI_URL, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    response_dict = resp.json()

    data = response_dict.get("data", {}) or {}

    profile_info = {
        "full_name": data.get("full_name"),
        "username": data.get("username"),
        "followers": data.get("follower_count"),
        "following": data.get("following_count"),
        "media_count": data.get("media_count"),
        "is_private": data.get("is_private"),
        "bio": data.get("biography"),
        "hashtags": [
            e["hashtag"]["name"]
            for e in data.get("biography_with_entities", {}).get("entities", [])
            if "hashtag" in e
        ],
        "profile_pic_url": data.get("hd_profile_pic_url_info", {}).get("url"),
        "category": data.get("category"),
        "is_verified": data.get("is_verified"),
        "external_url": data.get("external_url"),
    }

    return profile_info
