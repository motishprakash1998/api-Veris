# from .employee import (
#     CreateEmployeeSchema,
#     CreateEmployeeProfileSchema,
#     EmployeeProfileResponse, 
#     LoginSchema,
#     TokenResponse,
#     ChangePasswordSchema,
#     ForgotPasswordSchema,
#     ResetPasswordSchema,
#     EmployeeData,
#     EmployeeResponse,
#     EmployeeUpdateRequest,
#     EmployeeProfilePathResponse
    
# )


# __all__ =[
#     "CreateEmployeeSchema",
#     "CreateEmployeeProfileSchema",
#     "EmployeeProfileResponse",
#     "LoginSchema",
#     "TokenResponse",
#     "ChangePasswordSchema",
#     "ForgotPasswordSchema",
#     "ResetPasswordSchema",
#     "EmployeeData",
#     "EmployeeResponse",
#     "EmployeeUpdateRequest",
#     "EmployeeProfilePathResponse"
# ]


# src/routers/employees/schemas/__init__.py
"""
Public exports for the `src.routers.employees.schemas` package.

This file re-exports the schema classes defined in `employee.py` so callers can do:
    import src.routers.employees.schemas as schemas
    schemas.EmployeeData
"""

# Import the symbols from the concrete module where they're implemented.
# Adjust the module name below if your schema file is named differently.
from .employee import (
    # Enums & base schemas
    RoleEnum,
    StatusEnum,
    EmployeeBase,
    CreateEmployeeSchema,
    EmployeeResponseData,
    # Profile schemas
    EmployeeProfileBase,
    CreateEmployeeProfileSchema,
    EmployeeProfileResponse,
    # Combined / response schemas
    EmployeeProfileData,
    EmployeeData,
    EmployeeResponse,
    EmployeeProfilePathResponse,
    # Auth & misc
    LoginSchema,
    TokenResponse,
    ChangePasswordSchema,
    ForgotPasswordSchema,
    ResetPasswordSchema,
    UpdateProfilePathRequest,
    EmployeeUpdateRequest,
)

# Public API
__all__ = [
    # Enums & base schemas
    "RoleEnum",
    "StatusEnum",
    "EmployeeBase",
    "CreateEmployeeSchema",
    "EmployeeResponseData",
    # Profile schemas
    "EmployeeProfileBase",
    "CreateEmployeeProfileSchema",
    "EmployeeProfileResponse",
    # Combined / response schemas
    "EmployeeProfileData",
    "EmployeeData",
    "EmployeeResponse",
    "EmployeeProfilePathResponse",
    # Auth & misc
    "LoginSchema",
    "TokenResponse",
    "ChangePasswordSchema",
    "ForgotPasswordSchema",
    "ResetPasswordSchema",
    "UpdateProfilePathRequest",
    "EmployeeUpdateRequest",
]
