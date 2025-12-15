from sqlalchemy import Column, String, DateTime,Integer,Boolean
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func


Base = declarative_base()

class TwitterUser(Base):
    __tablename__ = "twitter_users"

    id = Column(Integer, primary_key=True)
    twitter_id = Column(String)  # Twitter user ID
    name = Column(String)
    username = Column(String)
    email = Column(String)
    profile_image_url = Column(String)

    access_token = Column(String)
    refresh_token = Column(String)
    token_expires_at = Column(DateTime)




class UserTwitterTimeline(Base):
    __tablename__ = "user_twitter_timelines"

    id = Column(Integer, primary_key=True, index=True)
    twitter_user_id = Column(String(50), index=True, nullable=False)
    tweet_id = Column(String(50), unique=True, index=True, nullable=False)
    text = Column(String)
    created_at = Column(String)
    language = Column(String(10))
    source = Column(String)
    likes = Column(Integer, default=0)
    replies = Column(Integer, default=0)
    retweets = Column(Integer, default=0)
    quotes = Column(Integer, default=0)
    bookmarks = Column(Integer, default=0)
    views = Column(String)
    is_promoted = Column(Boolean, default=False)
    in_reply_to = Column(JSONB)
    user = Column(JSONB)
    hashtags = Column(JSONB)
    mentions = Column(JSONB)
    urls = Column(JSONB)
    media = Column(JSONB)
    cursor_top = Column(String)
    cursor_bottom = Column(String)
    status = Column(Boolean, default=True)        # active / inactive
    is_deleted = Column(Boolean, default=False)   # soft delete
    created_at_db = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    inserted_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
