import requests
from sqlalchemy.orm import Session
from src.routers.social_media.models.x_models import UserTwitterTimeline

RAPID_API_KEY = "3ce8c354e3msh22662032620dd62p121c70jsn15208e443454"

def extract_timeline_data(timeline_json: dict) -> dict:
    """
    Extracts UI-ready valuable information from Twitter/X timeline JSON
    """

    output = {
        "tweets": [],
        "cursors": {
            "top": None,
            "bottom": None
        }
    }

    instructions = timeline_json.get("result", {}) \
        .get("timeline", {}) \
        .get("instructions", [])

    for instruction in instructions:
        if instruction.get("type") != "TimelineAddEntries":
            continue

        for entry in instruction.get("entries", []):

            # ---------------- CURSORS ----------------
            if entry.get("content", {}).get("entryType") == "TimelineTimelineCursor":
                cursor_type = entry["content"].get("cursorType")
                cursor_value = entry["content"].get("value")

                if cursor_type == "Top":
                    output["cursors"]["top"] = cursor_value
                elif cursor_type == "Bottom":
                    output["cursors"]["bottom"] = cursor_value
                continue

            # ---------------- TWEETS ----------------
            item = entry.get("content", {}) \
                .get("itemContent", {}) \
                .get("tweet_results", {}) \
                .get("result")

            if not item or item.get("__typename") != "Tweet":
                continue

            legacy = item.get("legacy", {})
            user = item.get("core", {}) \
                .get("user_results", {}) \
                .get("result", {}) \
                .get("legacy", {})

            # ---- MEDIA ----
            media_items = []
            for media in legacy.get("extended_entities", {}) \
                .get("media", []):

                media_items.append({
                    "media_url": media.get("media_url_https"),
                    "type": media.get("type"),
                    "width": media.get("original_info", {}).get("width"),
                    "height": media.get("original_info", {}).get("height"),
                })

            # ---- ENTITIES ----
            entities = legacy.get("entities", {})

            tweet_data = {
                "tweet_id": item.get("rest_id"),
                "text": legacy.get("full_text"),
                "created_at": legacy.get("created_at"),
                "language": legacy.get("lang"),
                "source": item.get("source"),

                # ---- COUNTS ----
                "likes": legacy.get("favorite_count", 0),
                "replies": legacy.get("reply_count", 0),
                "retweets": legacy.get("retweet_count", 0),
                "quotes": legacy.get("quote_count", 0),
                "bookmarks": legacy.get("bookmark_count", 0),
                "views": item.get("views", {}).get("count"),

                # ---- REPLY INFO ----
                "in_reply_to": {
                    "tweet_id": legacy.get("in_reply_to_status_id_str"),
                    "user_id": legacy.get("in_reply_to_user_id_str"),
                    "username": legacy.get("in_reply_to_screen_name"),
                },

                # ---- USER INFO ----
                "user": {
                    "user_id": legacy.get("user_id_str"),
                    "name": user.get("name"),
                    "username": user.get("screen_name"),
                    "bio": user.get("description"),
                    "location": user.get("location"),
                    "avatar": user.get("profile_image_url_https"),
                    "banner": user.get("profile_banner_url"),
                    "followers": user.get("followers_count"),
                    "following": user.get("friends_count"),
                    "verified": user.get("verified"),
                    "blue_verified": item.get("core", {}) \
                        .get("user_results", {}) \
                        .get("result", {}) \
                        .get("is_blue_verified", False)
                },

                # ---- ENTITIES ----
                "hashtags": [h.get("text") for h in entities.get("hashtags", [])],
                "mentions": [
                    {
                        "id": m.get("id_str"),
                        "username": m.get("screen_name"),
                        "name": m.get("name")
                    } for m in entities.get("user_mentions", [])
                ],
                "urls": [u.get("expanded_url") for u in entities.get("urls", [])],

                # ---- MEDIA ----
                "media": media_items,

                # ---- PROMOTED ----
                "is_promoted": entry.get("entryId", "").startswith("promoted-tweet")
            }

            output["tweets"].append(tweet_data)

    return output

def fetch_and_store_timeline(
    db: Session,
    twitter_user_id: str,
    count: int = 20
):
    url = "https://twitter241.p.rapidapi.com/user-media"

    headers = {
        "x-rapidapi-key": RAPID_API_KEY,
        "x-rapidapi-host": "twitter241.p.rapidapi.com"
    }

    response = requests.get(
        url,
        headers=headers,
        params={
            "user": twitter_user_id,
            "count": count
        }
    )

    if response.status_code != 200:
        raise ValueError("Twitter fetch failed")

    extracted = extract_timeline_data(response.json())

    for tweet in extracted["tweets"]:

        exists = (
            db.query(UserTwitterTimeline)
            .filter(
                UserTwitterTimeline.tweet_id == tweet["tweet_id"],
                UserTwitterTimeline.is_deleted == False
            )
            .first()
        )

        if exists:
            continue

        row = UserTwitterTimeline(
            twitter_user_id=twitter_user_id,

            tweet_id=tweet["tweet_id"],
            text=tweet["text"],
            created_at=tweet["created_at"],
            language=tweet["language"],
            source=tweet.get("source"),

            likes=tweet["likes"],
            replies=tweet["replies"],
            retweets=tweet["retweets"],
            quotes=tweet["quotes"],
            bookmarks=tweet["bookmarks"],
            views=tweet["views"],

            is_promoted=tweet["is_promoted"],

            in_reply_to=tweet["in_reply_to"],
            user=tweet["user"],

            hashtags=tweet["hashtags"],
            mentions=tweet["mentions"],
            urls=tweet["urls"],

            media=tweet["media"],

            cursor_top=extracted["cursors"]["top"],
            cursor_bottom=extracted["cursors"]["bottom"],

            status=True,
            is_deleted=False
        )

        db.add(row)

    db.commit()

    # EXACT SAME RESPONSE
    return {
        "tweets": extracted["tweets"],
        "cursors": extracted["cursors"]
    }
