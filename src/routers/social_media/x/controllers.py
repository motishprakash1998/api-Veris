# def extract_clean_user_info(raw):
#     try:
#         u = raw["user"]["result"]
#         legacy = u.get("legacy", {})

#         return {
#             "user_id": u.get("rest_id"),
#             "name": legacy.get("name"),
#             "username": legacy.get("screen_name"),
#             "description": legacy.get("description"),
#             "location": legacy.get("location"),
#             "profile_image": legacy.get("profile_image_url_https"),
#             "banner_image": legacy.get("profile_banner_url"),
#             "followers_count": legacy.get("followers_count"),
#             "following_count": legacy.get("friends_count"),
#             "media_count": legacy.get("media_count"),
#             "tweets_count": legacy.get("statuses_count"),
#             "verified": u.get("is_blue_verified") or legacy.get("verified"),
#             "url": legacy.get("url"),
#             "professional_category": (
#                 u.get("professional", {})
#                 .get("category", [{}])[0]
#                 .get("name")
#             ),
#             "account_created_at": legacy.get("created_at"),
#         }
#     except Exception as e:
#         return {"error": "Unable to parse user data", "details": str(e)}
