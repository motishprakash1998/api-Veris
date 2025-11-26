import re
import enum
import bcrypt
from sqlalchemy import (
    Column, Integer, String, Date, Enum as SAEnum, ForeignKey, TIMESTAMP, Text,
    Index, Boolean
)
from sqlalchemy.sql import func
from sqlalchemy.orm import validates, relationship, declarative_base

Base = declarative_base()

# =============================
# Enums
# =============================
class RoleEnum(enum.Enum):
    user = "user"
    superadmin = "superadmin"
    employee = "employee"


class StatusEnum(enum.Enum):
    active = "active"
    inactive = "inactive"
    waiting = "waiting"


class GenderEnum(enum.Enum):
    male = "male"
    female = "female"
    other = "other"


# =============================
# Users
# =============================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False)

    password_hash = Column(Text, nullable=False)

    role = Column(
        SAEnum(RoleEnum, name="role_enum", native_enum=True),
        nullable=False,
        default=RoleEnum.user,
    )

    status = Column(
        SAEnum(StatusEnum, name="status_enum", native_enum=True),
        nullable=False,
        default=StatusEnum.active,
    )

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    # Relationships
    profile = relationship(
        "UserProfile",
        uselist=False,
        back_populates="user",
        cascade="all, delete-orphan"
    )

    devices = relationship(
        "UserDevice",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    reset_tokens = relationship(
        "UserPasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # ---------- validation & helpers ----------
    @validates("email")
    def validate_email(self, key, email: str):
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email or ""):
            raise ValueError("Invalid email address")
        return email

    def set_password(self, raw_password: str):
        self.password_hash = bcrypt.hashpw(
            raw_password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

    def verify_password(self, raw_password: str) -> bool:
        return bcrypt.checkpw(
            raw_password.encode("utf-8"),
            self.password_hash.encode("utf-8")
        )

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role.value})>"


# Case-insensitive unique email
Index("idx_users_email_lower", func.lower(User.email), unique=True)


# =============================
# User Profile (1:1)
# =============================
class UserProfile(Base):
    __tablename__ = "users_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     unique=True, nullable=False)

    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone_number = Column(String(20), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(SAEnum(GenderEnum, name="gender_enum",
                           native_enum=True), nullable=True)
    address = Column(String(255), nullable=True)
    state = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    pin_code = Column(String(20), nullable=True)

    # New fields
    state_name = Column(String(150), nullable=True)
    pc_name = Column(String(150), nullable=True)
    profile_path = Column(Text, nullable=False,
                          default="profile_pictures/default.png")

    emergency_contact = Column(String(20), nullable=True)
    profile_completed = Column(Boolean, nullable=False, default=False)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    # Relationship
    user = relationship("User", back_populates="profile")

    @validates("phone_number", "emergency_contact")
    def validate_phone_e164(self, key, value):
        if value and not re.match(r"^\+?[1-9]\d{1,14}$", value):
            raise ValueError(f"Invalid {key} (must be E.164 format)")
        return value

    def __repr__(self):
        return f"<UserProfile(id={self.id}, user_id={self.user_id}, name={self.first_name} {self.last_name})>"


# =============================
# User Devices (FCM tokens / sessions)
# =============================
class UserDevice(Base):
    __tablename__ = "user_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False)

    fcm_token = Column(Text, nullable=False)
    last_seen_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="devices")

    def __repr__(self):
        return f"<UserDevice(id={self.id}, user_id={self.user_id})>"


# =============================
# Password Reset Tokens
# =============================
class UserPasswordResetToken(Base):
    __tablename__ = "user_password_reset_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False)

    token = Column(Text, nullable=False, unique=True)
    expires_at = Column(TIMESTAMP, nullable=False)
    used_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="reset_tokens")

    def __repr__(self):
        return f"<UserPasswordResetToken(id={self.id}, user_id={self.user_id})>"
