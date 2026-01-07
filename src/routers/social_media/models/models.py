from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean, DateTime,
    ForeignKey, JSON, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, mapped_column


Base = declarative_base()


class Platform(Base):
    __tablename__ = "platforms"

    id = Column(Integer, primary_key=True)
    code = Column(Text, nullable=False, unique=True)  # 'instagram', 'facebook', 'x', 'linkedin'
    display_name = Column(Text, nullable=False)

    social_accounts = relationship("SocialAccount", back_populates="platform")


class SocialAccount(Base):
    __tablename__ = "social_accounts"

    id = Column(BigInteger, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), nullable=False)
    platform_user_id = Column(Text, nullable=False)
    username = Column(Text)
    profile_url = Column(Text)
    is_verified = Column(Boolean)
    is_private = Column(Boolean)
    last_seen_at = Column(DateTime(timezone=True))
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    canonical = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("platform_id", "platform_user_id"),
        Index("idx_social_accounts_platform_username", "platform_id", "username"),
        Index("idx_social_accounts_platform_lastseen", "platform_id", "last_seen_at"),
    )

    platform = relationship("Platform", back_populates="social_accounts")
    profiles = relationship("AccountProfile", back_populates="social_account", cascade="all, delete-orphan")
    snapshots = relationship("AccountSnapshot", back_populates="social_account", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="social_account", cascade="all, delete-orphan")
    privacy_flags = relationship("PrivacyFlag", back_populates="social_account", cascade="all, delete-orphan")


class AccountProfile(Base):
    __tablename__ = "account_profiles"

    id = Column(BigInteger, primary_key=True)
    social_account_id = Column(BigInteger, ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False)
    display_name = Column(Text)
    bio = Column(Text)
    location = Column(Text)
    website = Column(Text)
    profile_image_url = Column(Text)
    follower_count = Column(BigInteger)
    following_count = Column(BigInteger)
    post_count = Column(BigInteger)
    is_private = Column(Boolean)
    extra = Column(JSON)
    source = Column(Text)  # 'api', 'scrape', 'upload'
    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    retrieved_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    __table_args__ = (
    Index(
        "idx_account_profiles_social_on_retrieved",
        "social_account_id",
        "retrieved_at"
    ),
)


    social_account = relationship("SocialAccount", back_populates="profiles")


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"

    id = Column(BigInteger, primary_key=True)
    social_account_id = Column(BigInteger, ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False)
    snapshot_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    follower_count = Column(BigInteger)
    following_count = Column(BigInteger)
    post_count = Column(BigInteger)
    extra = Column(JSON)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint("social_account_id", "snapshot_at"),
        Index("idx_account_snapshots_account_time", "social_account_id", "snapshot_at"),
    )

    social_account = relationship("SocialAccount", back_populates="snapshots")


class Post(Base):
    __tablename__ = "posts"

    id = Column(BigInteger, primary_key=True)
    social_account_id = Column(BigInteger, ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False)
    platform_post_id = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True))
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
    text = Column(Text)
    language = Column(Text)
    is_reply = Column(Boolean, default=False)
    in_reply_to_post_id = Column(Text)
    is_repost = Column(Boolean, default=False)
    extra = Column(JSON)
    raw_response = Column(JSON)

    __table_args__ = (
        UniqueConstraint("social_account_id", "platform_post_id"),
        Index("idx_posts_account_created", "social_account_id", "created_at"),
        Index("idx_posts_platform_postid", "platform_post_id"),
    )

    social_account = relationship("SocialAccount", back_populates="posts")
    media = relationship("PostMedia", back_populates="post", cascade="all, delete-orphan")
    metrics = relationship("PostMetric", back_populates="post", cascade="all, delete-orphan")
    mentions = relationship("Mention", back_populates="mentioning_post", cascade="all, delete-orphan")
    engagements = relationship("Engagement", back_populates="post", cascade="all, delete-orphan")

class PostMedia(Base):
    __tablename__ = "post_media"

    id = Column(BigInteger, primary_key=True)
    post_id = Column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    media_type = Column(Text)  # 'image','video','gif'
    media_url = Column(Text)
    alt_text = Column(Text)
    media_metadata = Column("metadata", JSON)  # ✅ DB column is "metadata", Python attr is "media_metadata"

    post = relationship("Post", back_populates="media")



class PostMetric(Base):
    __tablename__ = "post_metrics"

    id = Column(BigInteger, primary_key=True)
    post_id = Column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    snapshot_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    like_count = Column(BigInteger)
    share_count = Column(BigInteger)
    comment_count = Column(BigInteger)
    view_count = Column(BigInteger)
    extra = Column(JSON)

    __table_args__ = (
        UniqueConstraint("post_id", "snapshot_at"),
        Index("idx_post_metrics_post_time", "post_id", "snapshot_at"),
    )

    post = relationship("Post", back_populates="metrics")


class FollowersEdge(Base):
    __tablename__ = "followers_edges"

    id = Column(BigInteger, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), nullable=False)
    follower_account_id = Column(BigInteger, ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False)
    followed_account_id = Column(BigInteger, ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    relation_status = Column(Text, default="following")  # 'following', 'requested', 'blocked'
    extra = Column(JSON)

    __table_args__ = (
        UniqueConstraint("platform_id", "follower_account_id", "followed_account_id", "observed_at"),
        Index("idx_followers_edges_pair", "platform_id", "follower_account_id", "followed_account_id"),
    )


class Mention(Base):
    __tablename__ = "mentions"

    id = Column(BigInteger, primary_key=True)
    mentioned_account_id = Column(BigInteger, ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False)
    mentioning_post_id = Column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    mention_text = Column(Text)
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    extra = Column(JSON)

    mentioning_post = relationship("Post", back_populates="mentions")


class Engagement(Base):
    __tablename__ = "engagements"

    id = Column(BigInteger, primary_key=True)
    post_id = Column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    engagement_type = Column(Text, nullable=False)  # 'like','comment','reaction','retweet'
    actor_account_id = Column(BigInteger, ForeignKey("social_accounts.id"))
    actor_platform_user_id = Column(Text)
    content = Column(Text)  # comment body if any
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    raw = Column(JSON)

    __table_args__ = (
        Index("idx_engagements_post", "post_id"),
    )

    post = relationship("Post", back_populates="engagements")


class FetchJob(Base):
    __tablename__ = "fetch_jobs"

    id = Column(BigInteger, primary_key=True)
    job_type = Column(Text, nullable=False)  # 'profile_fetch','posts_fetch','followers_fetch'
    platform_id = Column(Integer, ForeignKey("platforms.id"), nullable=False)
    target_identifier = Column(Text)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    status = Column(Text)  # 'pending','success','failed','rate_limited'
    rate_limit_reset_at = Column(DateTime(timezone=True))
    note = Column(Text)

    raw_responses = relationship("RawApiResponse", back_populates="fetch_job", cascade="all, delete-orphan")


class RawApiResponse(Base):
    __tablename__ = "raw_api_responses"

    id = Column(BigInteger, primary_key=True)
    fetch_job_id = Column(BigInteger, ForeignKey("fetch_jobs.id", ondelete="SET NULL"))
    platform_id = Column(Integer, ForeignKey("platforms.id"), nullable=False)
    endpoint = Column(Text)
    response_code = Column(Integer)
    response_json = Column(JSON)
    received_at = Column(DateTime(timezone=True), server_default=func.now())

    fetch_job = relationship("FetchJob", back_populates="raw_responses")


class PrivacyFlag(Base):
    __tablename__ = "privacy_flags"

    id = Column(BigInteger, primary_key=True)
    social_account_id = Column(BigInteger, ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False)
    flag_type = Column(Text, nullable=False)  # 'private_account', 'consent_given', 'gdpr_request'
    details = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    social_account = relationship("SocialAccount", back_populates="privacy_flags")
