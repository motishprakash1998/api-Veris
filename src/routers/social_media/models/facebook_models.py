from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, TIMESTAMP
from sqlalchemy.orm import declarative_base
from sqlalchemy import ForeignKey

# Base = declarative_base()
from src.database.dbbase import Base

class FacebookUser(Base):
    __tablename__ = "facebook_users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    fb_user_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(255))
    email = Column(String(255))
    picture_url = Column(Text)
    fb_page_id = Column(Text, unique=True, nullable=True)
    access_token = Column(Text)
    token_expires_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
