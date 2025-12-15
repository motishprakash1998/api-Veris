import enum
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict


# =============================
# Enums
# =============================
class RoleEnum(str, enum.Enum):
    user = "user"


class StatusEnum(str, enum.Enum):
    active = "active"
    inactive = "inactive"


# =============================
# User Base Schema
# =============================
class UserBase(BaseModel):
    full_name: str = Field(...)
    email: EmailStr
    password: str = Field(..., min_length=8)


# Create User Schema
class CreateUserSchema(UserBase):
    phone_number: Optional[str] = Field(None, pattern=r"^\+?[1-9]\d{1,14}$")


# =============================
# User Response (users table)
# =============================
class UserResponseData(BaseModel):
    id: int
    email: EmailStr
    role: RoleEnum
    status: StatusEnum
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =============================
# User Profile Base
# =============================
class UserProfileBase(BaseModel):
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    phone_number: Optional[str] = Field(None, pattern=r"^\+?[1-9]\d{1,14}$")

    date_of_birth: Optional[date] = None
    gender: Optional[str] = Field(None, pattern="^(male|female|other)$")

    address: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    pin_code: Optional[str] = None

    profile_path: Optional[str] = "profile_pictures/default.png"

    emergency_contact: Optional[str] = Field(None, pattern=r"^\+?[1-9]\d{1,14}$")

    profile_completed: Optional[int] = Field(0, ge=0, le=1)

    model_config = ConfigDict(from_attributes=True)


# Create User Profile Schema
class CreateUserProfileSchema(UserProfileBase):
    user_id: int


# User Profile Response
class UserProfileResponse(BaseModel):
    id: int
    user_id: int
    first_name: str
    last_name: str
    phone_number: Optional[str]
    date_of_birth: Optional[date]
    gender: Optional[str]
    address: Optional[str]
    state: Optional[str]
    country: Optional[str]
    pin_code: Optional[str]
    profile_path: Optional[str]
    emergency_contact: Optional[str]
    profile_completed: int
    state_name: Optional[str] = None
    pc_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =============================
# Login
# =============================
class LoginSchema(BaseModel):
    email: EmailStr
    password: str


# Token Response
class TokenResponse(BaseModel):
    success: bool
    status: int
    isActive: bool
    message: str
    data: Optional[dict]


# =============================
# Password Management
# =============================
class ChangePasswordSchema(BaseModel):
    old_password: str
    new_password: str


class ForgotPasswordSchema(BaseModel):
    email: EmailStr


class ResetPasswordSchema(BaseModel):
    token: str
    new_password: str


# =============================
# Update Profile Path Only
# =============================
class UpdateProfilePathRequest(BaseModel):
    profile_path: str


# =============================
# Combined User Profile Data
# =============================
class UserProfileData(BaseModel):
    first_name: str
    last_name: str
    phone_number: Optional[str]
    date_of_birth: Optional[datetime]
    gender: Optional[str]
    address: Optional[str]
    state_name: Optional[str] = Field(alias="state")   # accept "state" as input
    pc_name: Optional[str] = Field(alias="pin_code")   # accept "pin_code" as input
    country: Optional[str]
    profile_path: Optional[str]
    emergency_contact: Optional[str]
    profile_completed: bool = False
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {
        "populate_by_name": True,   # allow access by field name, and accept aliases
        "from_attributes": True     # if you want to validate from ORM objects
    }


class UserData(BaseModel):
    id: int
    email: EmailStr
    role: RoleEnum
    status: StatusEnum
    created_at: datetime
    updated_at: datetime
    twitter_login: bool
    twitter_id: Optional[str]
    profile: Optional[UserProfileData]

    model_config = ConfigDict(from_attributes=True)


# User Response Wrapper
class UserResponse(BaseModel):
    success: bool
    status: int
    isActive: bool
    message: str
    data: UserData


# =============================
# Profile Path Response
# =============================
class UserProfilePathResponse(BaseModel):
    success: bool
    status: int
    message: str
    data: dict


# =============================
# Update User Request
# =============================
class UserUpdateRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    profile_path: Optional[str] = None
    address: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    pin_code: Optional[str] = None
    state_name: Optional[str] = None
    pc_name: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    emergency_contact: Optional[str] = None
    role: Optional[RoleEnum] = None  # Only superadmin can update role
