import enum
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, EmailStr, Field, root_validator,ConfigDict


# Enum for Employee Roles
class RoleEnum(str, enum.Enum):
    employee = "employee"
    superadmin = "superadmin"

# Enum for Employee Status
class StatusEnum(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    waiting = "waiting"


# Base Schema for Employees table
class EmployeeBase(BaseModel):
    full_name: str = Field(...)
    email: EmailStr
    password: str = Field(..., min_length=8)


#  CreateEmployeeSchema inherits from EmployeeBase
class CreateEmployeeSchema(EmployeeBase):
    phone_number: Optional[str] = Field(None, pattern=r"^\+?[1-9]\d{1,14}$")


#  Employee Response Schema (Employees table)
class EmployeeResponseData(BaseModel):
    id: int
    email: EmailStr
    role: RoleEnum
    status: StatusEnum
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
        json_encoders = {datetime: lambda v: v.isoformat()}


#  Base Schema for Employee Profiles table
class EmployeeProfileBase(BaseModel):
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    phone_number: Optional[str] = Field(None, pattern=r"^\+?[1-9]\d{1,14}$")
    date_of_birth: Optional[datetime] = None
    gender: Optional[str] = Field(None, pattern="^(male|female|other)$")
    address: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    pin_code: Optional[str] = None
    profile_path: Optional[str] = "profile_pictures/default.png"

    # Patient/General fields
    emergency_contact: Optional[str] = Field(None, pattern=r"^\+?[1-9]\d{1,14}$")

    # 0 or 1 indicating completion
    profile_completed: Optional[int] = Field(0, ge=0, le=1)

    class Config:
        orm_mode = True


#  Create Profile Schema
class CreateEmployeeProfileSchema(EmployeeProfileBase):
    employee_id: int


#  Employee Profile Response Schema
class EmployeeProfileResponse(BaseModel):
    id: int
    employee_id: int
    first_name: str
    last_name: str
    phone_number: Optional[str]
    date_of_birth: Optional[datetime]
    gender: Optional[str]
    address: Optional[str]
    state: Optional[str]
    country: Optional[str]
    pin_code: Optional[str]
    profile_path: Optional[str]
    emergency_contact: Optional[str]
    profile_completed: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
        json_encoders = {datetime: lambda v: v.isoformat()}


#  Employee Login Schema
class LoginSchema(BaseModel):
    email: EmailStr
    password: str

#  Token Response (For Authentication)
class TokenResponse(BaseModel):
    success: bool
    status: int
    isActive: bool
    message: str
    data: Optional[dict]  # Data can be None or a dictionary


#  Change Password Schema
class ChangePasswordSchema(BaseModel):
    old_password: str
    new_password: str


#  Forgot Password Schema
class ForgotPasswordSchema(BaseModel):
    email: EmailStr


#  Reset Password Schema
class ResetPasswordSchema(BaseModel):
    token: str
    new_password: str


#  Update Profile Path Schema
class UpdateProfilePathRequest(BaseModel):
    profile_path: str


#  Combined Employee Data Response (Employee + Profile)
class EmployeeProfileData(BaseModel):
    first_name: Optional[str]
    last_name: Optional[str]
    phone_number: Optional[str]
    date_of_birth: Optional[datetime]
    gender: Optional[str]
    address: Optional[str]
    state: Optional[str]
    country: Optional[str]
    pin_code: Optional[str]
    profile_path: Optional[str]
    state_name: Optional[str]
    pc_name: Optional[str]
    emergency_contact: Optional[str]
    profile_completed: Optional[bool]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EmployeeData(BaseModel):
    id: int
    email: EmailStr
    role: RoleEnum
    status: StatusEnum
    created_at: datetime
    updated_at: datetime
    profile: Optional[EmployeeProfileData]   # 👈 nested profile

    model_config = ConfigDict(from_attributes=True)


#  General Employee Response Wrapper
class EmployeeResponse(BaseModel):
    success: bool
    status: int
    isActive: bool
    message: str
    data: EmployeeData


#  Profile Path Response
class EmployeeProfilePathResponse(BaseModel):
    success: bool
    status: int
    message: str
    data: dict


#  Employee Update Request
class EmployeeUpdateRequest(BaseModel):
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
    role: Optional[RoleEnum] = None  # Only superadmins can update this
