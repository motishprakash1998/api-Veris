from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class FacebookUserBase(BaseModel):
    fb_user_id: str
    name: Optional[str] = None
    email: Optional[str] = None
    picture_url: Optional[str] = None
    fb_page_id: str
    access_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None

class FacebookUserCreate(FacebookUserBase):
    pass

class FacebookUserResponse(FacebookUserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
