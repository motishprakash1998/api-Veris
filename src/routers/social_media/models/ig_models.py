# src/models/instagram_user.py

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from src.database.dbbase import Base

class InstagramUser(Base):
    __tablename__ = "instagram_users"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    username = Column(String(255), nullable=False)
    profile_url = Column(String(500), nullable=False)

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_instagram_user_per_user"),
    )
