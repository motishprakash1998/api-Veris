from sqlalchemy import Column, String, DateTime,Integer
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class TwitterUser(Base):
    __tablename__ = "twitter_users"

    id = Column(Integer, primary_key=True)
    twitter_id = Column(String, primary_key=True)  # Twitter user ID
    name = Column(String)
    username = Column(String)
    email = Column(String)
    profile_image_url = Column(String)

    access_token = Column(String)
    refresh_token = Column(String)
    token_expires_at = Column(DateTime)
