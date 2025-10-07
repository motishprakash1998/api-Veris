from typing import List, Optional
from pydantic import BaseModel

# --- Pydantic Schemas (Response Models) ---
class AccountProfileSchema(BaseModel):
    id: int
    display_name: Optional[str]
    bio: Optional[str]
    website: Optional[str]
    location: Optional[str]
    follower_count: Optional[int]
    following_count: Optional[int]
    post_count: Optional[int]
    like_count: Optional[int]
    source: Optional[str]
    profile_image_url : Optional[str]
    retrieved_at: Optional[str]

    class Config:
        orm_mode = True


class SocialAccountSchema(BaseModel):
    id: int
    platform_user_id: str
    username: Optional[str]
    profile_url: Optional[str]
    is_verified: Optional[bool]
    is_private: Optional[bool]
    canonical: Optional[bool]
    platform: Optional[str]
    profiles: List[AccountProfileSchema] = []

    class Config:
        orm_mode = True


class SocialInfoResponse(BaseModel):
    social_accounts: List[SocialAccountSchema]