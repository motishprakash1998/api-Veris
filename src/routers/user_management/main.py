import os
import uuid
import boto3
import urllib.parse
from sqlalchemy import func
from sqlalchemy.orm import Session
from loguru import logger as logging
from datetime import datetime, timedelta
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from fastapi import (
    APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query,
    Request, UploadFile, status
)
from fastapi.security import OAuth2PasswordBearer

from . import models, schemas, controller
from src.database import get_db
from src.utils.jwt import (
    create_access_token, create_refresh_token, get_email_from_token
)
from src.utils.jwt import verify_password  # optional helper; prefer instance method if present
from src.utils.email_service import send_account_creation_email

load_dotenv()

# Defining the router
router = APIRouter(
    prefix="/api/users",
    tags=["Users"],
    responses={404: {"description": "Not found"}},
)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# ----------------------
# Login
# ----------------------
@router.post("/login", response_model=schemas.TokenResponse)
def login(credentials: schemas.LoginSchema = Body(...), db: Session = Depends(get_db)):
    logging.debug("Login endpoint called for email: %s", credentials.email)
    try:
        user = (
            db.query(models.User)
            .filter(func.lower(models.User.email) == func.lower(credentials.email))
            .first()
        )

        if not user:
            logging.warning("Login failed: user not found: %s", credentials.email)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "success": False,
                    "status": 401,
                    "isActive": False,
                    "message": "The email you entered does not match any account. Please check and try again.",
                    "data": None,
                },
            )

        # extract status string safely
        status_val = getattr(user.status, "value", str(user.status))

        # check account state
        if status_val == "waiting":
            logging.info("Login blocked: account under review for %s", user.email)
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "success": False,
                    "status": 403,
                    "isActive": False,
                    "message": "Your request is under review, please wait for approval.",
                    "data": None,
                },
            )

        if status_val != "active":
            logging.warning("Login blocked: inactive account for %s", user.email)
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "success": False,
                    "status": 403,
                    "isActive": False,
                    "message": "Your account is not active. Please contact support.",
                    "data": None,
                },
            )

        # verify password (prefer instance method if available)
        password_ok = False
        if hasattr(user, "verify_password"):
            password_ok = user.verify_password(credentials.password)
        else:
            # fallback to util verify_password(raw, hashed)
            password_ok = verify_password(credentials.password, user.password_hash)

        if not password_ok:
            logging.warning("Login failed: bad password for %s", credentials.email)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "success": False,
                    "status": 401,
                    "isActive": False,
                    "message": "The password you entered is incorrect. Please try again.",
                    "data": None,
                },
            )

        role_obj = user.role
        role_str = getattr(role_obj, "value", None) or getattr(role_obj, "name", None) or str(role_obj)

        access_token = create_access_token(data={"sub": user.email, "role": role_str})
        refresh_token = create_refresh_token(data={"sub": user.email, "role": role_str})

        logging.info("User %s logged in successfully", user.email)
        return {
            "success": True,
            "status": 200,
            "isActive": True,
            "message": "Login successful. Welcome back!",
            "data": {
                "email_id": user.email,
                "role": role_str,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
            },
        }

    except Exception as e:
        logging.exception("An error occurred during login")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "status": 500,
                "isActive": False,
                "message": "An unexpected error occurred. Please try again later.",
                "data": None,
            },
        )


# ----------------------
# Get user info (from token)
# ----------------------
@router.get("/info", response_model=schemas.UserResponse)
def get_info(request: Request, db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    """
    Fetch user information using the JWT token.
    """
    try:
        # prefer Authorization header (keeps compatibility with Bearer <token>)
        auth_header = request.headers.get("Authorization")
        if auth_header:
            if not auth_header.startswith("Bearer "):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid token format. Token must start with 'Bearer'.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            raw_token = auth_header.split(" ", 1)[1]
        else:
            # oauth2_scheme already extracted token, use that
            raw_token = token

        email = get_email_from_token(raw_token)
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = db.query(models.User).filter(func.lower(models.User.email) == (email or "").lower()).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        if user.status != models.StatusEnum.active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your account is inactive. Please contact support.")

        profile = db.query(models.UserProfile).filter(models.UserProfile.user_id == user.id).first()

        profile_data = None
        if profile:
            profile_data = schemas.UserProfileData(
                first_name=profile.first_name,
                last_name=profile.last_name,
                phone_number=profile.phone_number,
                profile_path=profile.profile_path or "profile_pictures/default.png",
                date_of_birth=profile.date_of_birth,
                gender=profile.gender.value if profile.gender else None,
                address=profile.address,
                state=profile.state,
                country=profile.country,
                pin_code=profile.pin_code,
                emergency_contact=profile.emergency_contact,
                profile_completed=bool(profile.profile_completed),
                created_at=profile.created_at,
                updated_at=profile.updated_at,
            )

        user_data = schemas.UserData(
            id=user.id,
            email=user.email,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            status=user.status.value if hasattr(user.status, "value") else str(user.status),
            created_at=user.created_at,
            updated_at=user.updated_at,
            profile=profile_data,
        )

        return schemas.UserResponse(
            success=True,
            status=200,
            isActive=(user.status == models.StatusEnum.active),
            message="User found successfully",
            data=user_data,
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Unexpected error in /info")
        raise HTTPException(status_code=500, detail="An unexpected error occurred. Please try again later.")


# ----------------------
# Create user
# ----------------------
@router.post("/create", response_model=schemas.TokenResponse, status_code=status.HTTP_201_CREATED)
def create_user(background_tasks: BackgroundTasks, payload: schemas.CreateUserSchema, db: Session = Depends(get_db)):
    try:
        logging.info("User creation attempt for email: %s", payload.email)

        existing = (
            db.query(models.User)
            .filter(func.lower(models.User.email) == func.lower(payload.email))
            .first()
        )
        if existing:
            logging.warning("User creation failed: Email %s already exists", payload.email)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="An account with this email already exists. Please use a different email.")

        name_parts = payload.full_name.strip().split(maxsplit=1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        new_user = models.User(
            email=payload.email,
            role=models.RoleEnum.user,
            status=models.StatusEnum.active,
        )
        new_user.set_password(payload.password)

        profile = models.UserProfile(
            user=new_user,
            first_name=first_name,
            last_name=last_name,
            phone_number=payload.phone_number,
            profile_path="profile_pictures/default.png",
            profile_completed=False,
        )

        db.add(new_user)
        db.add(profile)

        try:
            db.commit()
            db.refresh(new_user)
            db.refresh(profile)
        except Exception:
            db.rollback()
            logging.exception("Database commit failed during user creation")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while creating the user. Please try again.")

        # send welcome/approval email in background
        background_tasks.add_task(send_account_creation_email, new_user.email, f"{first_name} {last_name}")

        profile_payload = {
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "phone_number": profile.phone_number,
            "date_of_birth": profile.date_of_birth,
            "gender": (profile.gender.value if getattr(profile, "gender", None) else profile.gender),
            "address": profile.address,
            "state": profile.state,
            "country": profile.country,
            "pin_code": profile.pin_code,
            "profile_path": profile.profile_path,
            "emergency_contact": profile.emergency_contact,
            "profile_completed": bool(profile.profile_completed),
            "created_at": profile.created_at,
            "updated_at": profile.updated_at
        }
        profile_data = schemas.UserProfileData(**profile_payload)

        user_data = schemas.UserData(
            id=new_user.id,
            email=new_user.email,
            role=new_user.role.value,
            status=new_user.status.value,
            created_at=new_user.created_at,
            updated_at=new_user.updated_at,
            profile=profile_data,
        )

        logging.info("User %s created successfully with role '%s'", new_user.email, new_user.role.value)

        if new_user.status == models.StatusEnum.active:
            access_token = create_access_token(data={"sub": new_user.email, "role": new_user.role.value})
            return schemas.TokenResponse(
                success=True,
                status=status.HTTP_201_CREATED,
                isActive=True,
                message="User account created and activated successfully.",
                data={
                    "user": user_data.dict(),
                    "access_token": access_token,
                    "token_type": "bearer",
                },
            )
        else:
            return schemas.TokenResponse(
                success=True,
                status=status.HTTP_201_CREATED,
                isActive=False,
                message="User account created successfully and is pending admin approval.",
                data={"user": user_data.dict()},
            )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        logging.exception("Unexpected error during user creation")
        db.rollback()
        raise HTTPException(status_code=500, detail="An unexpected error occurred. Please try again later.")


# ----------------------
# Get profile path (public URL)
# ----------------------
@router.get("/get-profile-path", response_model=schemas.UserProfilePathResponse)
def get_profile_path(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        email = get_email_from_token(token)
        if not email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})

        profile = (
            db.query(models.UserProfile)
            .join(models.User, models.UserProfile.user_id == models.User.id)
            .filter(func.lower(models.User.email) == (email or "").lower())
            .first()
        )

        if not profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found. Ensure the token is valid and try again.")

        profile_path = profile.profile_path or "profile_pictures/default.png"
        logging.info("Found profile path for user_id=%s: %s", profile.user_id, profile_path)

        source_bucket_name = os.environ.get("SOURCE_BUCKET_NAME")
        if not source_bucket_name:
            logging.warning("SOURCE_BUCKET_NAME env var not set; returning path without domain")
            public_url = profile_path
        else:
            public_url = controller.generate_presigned_url(source_bucket_name, profile_path)

        return schemas.UserProfilePathResponse(
            success=True,
            status=200,
            message="User profile path fetched successfully.",
            data={
                "profile_path": profile_path,
                "public_url": public_url,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Unexpected error in get_profile_path")
        raise HTTPException(status_code=500, detail="An unexpected error occurred. Please try again later.")


# ----------------------
# Update profile picture
# ----------------------
@router.put("/update-profile-path", response_model=schemas.UserResponse)
async def update_profile_path(profile_picture: UploadFile = File(...), token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        # decode token
        try:
            email = get_email_from_token(token)
            if not email:
                raise ValueError("Empty email in token")
        except HTTPException:
            raise
        except Exception as e:
            logging.error("Token decoding failed: %s", e)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})

        user = db.query(models.User).filter(func.lower(models.User.email) == (email or "").lower()).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found. Ensure the token is valid and try again.")

        profile = db.query(models.UserProfile).filter(models.UserProfile.user_id == user.id).first()
        if not profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found. Please create a profile before uploading a picture.")

        if profile_picture.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file type. Only JPEG and PNG are allowed.")

        bucket_name = os.environ.get("S3_BUCKET_NAME", "ai-interview-bot")
        region = os.environ.get("S3_REGION", "us-east-1")

        original_name = profile_picture.filename or "upload"
        _, ext = os.path.splitext(original_name)
        ext = ext.lower() if ext else ""
        unique_name = f"{uuid.uuid4().hex}{ext}"
        file_key = f"profile_pictures/{user.email}/{unique_name}"

        try:
            s3_client = boto3.client("s3", region_name=region)
            file_bytes = await profile_picture.read()
            s3_client.put_object(
                Bucket=bucket_name,
                Key=file_key,
                Body=file_bytes,
                ContentType=profile_picture.content_type,
            )
            logging.info("Uploaded profile picture to S3: s3://%s/%s", bucket_name, file_key)
        except Exception as s3_err:
            logging.exception("Error uploading file to S3: %s", s3_err)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to upload the profile picture to S3. Please try again.")

        profile.profile_path = file_key

        try:
            db.add(profile)
            db.commit()
            db.refresh(profile)
            db.refresh(user)
        except Exception as db_err:
            db.rollback()
            logging.exception("Database commit failed when updating profile_path: %s", db_err)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while updating the profile path. Please try again.")

        profile_completed_val = None
        if profile.profile_completed is not None:
            if isinstance(profile.profile_completed, bool):
                profile_completed_val = int(profile.profile_completed)
            else:
                try:
                    profile_completed_val = int(profile.profile_completed)
                except Exception:
                    profile_completed_val = 0

        # Build nested profile data for response
        profile_data = schemas.UserProfileData(
            first_name=profile.first_name,
            last_name=profile.last_name,
            phone_number=profile.phone_number,
            date_of_birth=profile.date_of_birth,
            gender=profile.gender.value if (profile.gender and hasattr(profile.gender, "value")) else (profile.gender if profile else None),
            address=profile.address,
            state=profile.state,
            country=profile.country,
            pin_code=profile.pin_code,
            profile_path=profile.profile_path,
            emergency_contact=profile.emergency_contact,
            profile_completed=bool(profile_completed_val),
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            state_name=getattr(profile, "state_name", None),
            pc_name=getattr(profile, "pc_name", None),
        )

        user_data = schemas.UserData(
            id=user.id,
            email=user.email,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            status=user.status.value if hasattr(user.status, "value") else str(user.status),
            created_at=user.created_at,
            updated_at=user.updated_at,
            profile=profile_data,
        )

        return schemas.UserResponse(
            success=True,
            status=200,
            isActive=(user.status == models.StatusEnum.active),
            message="User profile path updated successfully.",
            data=user_data,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Unexpected error in update_profile_path: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred. Please try again later.")


# ----------------------
# Update user info
# ----------------------
@router.put("/update-user-info", response_model=schemas.UserResponse)
def update_info(updated_info: schemas.UserUpdateRequest = Body(...), token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        try:
            email = get_email_from_token(token)
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})

        user = db.query(models.User).filter(func.lower(models.User.email) == (email or "").lower()).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found. Please ensure your token is valid.")

        if not user.profile:
            # ensure profile instance exists
            user.profile = models.UserProfile(user_id=user.id)
        profile = user.profile

        # update allowed fields
        for field, value in updated_info.dict(exclude_unset=True).items():
            if field in [
                "first_name", "last_name", "phone_number", "profile_path", "address",
                "state", "country", "pin_code", "gender", "emergency_contact",
                "state_name", "pc_name"
            ]:
                if value is None or (isinstance(value, str) and not value.strip()):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field.replace('_', ' ').title()} cannot be empty.")
                if field in ["phone_number", "emergency_contact"]:
                    # keep E.164 or 10-digit validation consistent with schemas
                    if not value.isdigit() or len(value) not in (10,):
                        # allow E.164 in schemas, but keep earlier 10-digit check fallback
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field.replace('_', ' ').title()} must be a 10-digit number (or E.164).")
                if field == "gender":
                    allowed_genders = ["male", "female", "other"]
                    if value.lower() not in allowed_genders:
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Gender must be one of: {', '.join(allowed_genders)}.")
                    value = value.lower()
                setattr(profile, field, value)

            elif field == "date_of_birth":
                try:
                    parsed = datetime.strptime(value, "%d/%m/%Y").date()
                    setattr(profile, field, parsed)
                except Exception:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use DD/MM/YYYY.")

            elif field == "role":
                # only allow admins to update role
                if user.role != models.RoleEnum.superadmin:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can update roles.")
                setattr(user, field, value)

            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Field '{field}' cannot be updated.")

        required_fields = [
            profile.first_name, profile.last_name, profile.phone_number,
            profile.profile_path, profile.address, profile.state,
            profile.country, profile.pin_code, profile.gender,
            profile.date_of_birth, profile.emergency_contact,
        ]
        profile.profile_completed = bool(all(required_fields))

        try:
            db.commit()
            db.refresh(user)
            db.refresh(profile)
        except Exception as e:
            db.rollback()
            logging.exception("Update failed: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while updating user information.")

        return schemas.UserResponse(
            success=True,
            status=200,
            isActive=(user.status == models.StatusEnum.active),
            message="User information updated successfully",
            data=schemas.UserData.from_orm(user),
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.exception("Unexpected error in update_info: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred. Please try again later.")


# ----------------------
# Change password
# ----------------------
@router.post("/change-password", status_code=200)
def change_password(change_request: schemas.ChangePasswordSchema, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        try:
            email = get_email_from_token(token)
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})

        user = db.query(models.User).filter(func.lower(models.User.email) == (email or "").lower()).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found. Ensure the token is valid and try again.")

        if not user.verify_password(change_request.old_password):
            logging.warning("Password change failed: Incorrect old password for %s", user.email)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The old password is incorrect.")

        if len(change_request.new_password) < 8:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The new password must be at least 8 characters long.")

        user.set_password(change_request.new_password)
        db.commit()

        logging.info("Password changed successfully for %s", user.email)
        return {
            "success": True,
            "status": 200,
            "isActive": (user.status == models.StatusEnum.active),
            "message": "Password changed successfully.",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logging.exception("Unexpected error during password change: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred. Please try again later.")


# ----------------------
# Forgot password
# ----------------------
@router.post("/forgot-password", status_code=200)
def forgot_password(forgot_request: schemas.ForgotPasswordSchema, db: Session = Depends(get_db)):
    try:
        user = db.query(models.User).filter(func.lower(models.User.email) == func.lower(forgot_request.email)).first()
        if not user:
            logging.warning("Forgot password: No user found with %s", forgot_request.email)
            return {
                "success": False,
                "status": 404,
                "isActive": False,
                "message": "No user found with this email address.",
                "data": None,
            }

        reset_token = create_access_token(data={"sub": user.email}, expires_delta=timedelta(hours=1))
        controller.send_password_reset_email(email=user.email, token=reset_token)

        logging.info("Password reset token sent to %s", user.email)
        return {
            "success": True,
            "status": 200,
            "isActive": (user.status == models.StatusEnum.active),
            "message": "A password reset link has been sent to your email.",
            "data": None,
        }

    except Exception as e:
        logging.exception("Forgot password error: %s", e)
        return {
            "success": False,
            "status": 500,
            "isActive": False,
            "message": "An unexpected error occurred. Please try again later.",
            "data": None,
        }


# ----------------------
# Reset password
# ----------------------
@router.post("/reset-password", status_code=200)
def reset_password(reset_request: schemas.ResetPasswordSchema, db: Session = Depends(get_db)):
    try:
        token_data = controller.decode_access_token(reset_request.token)
        email = token_data.get("sub")
        if not email:
            return {
                "success": False,
                "status": 400,
                "isActive": False,
                "message": "Invalid or expired token.",
                "data": None,
            }

        user = db.query(models.User).filter(func.lower(models.User.email) == func.lower(email)).first()
        if not user:
            return {
                "success": False,
                "status": 404,
                "isActive": False,
                "message": "No user found with this email address.",
                "data": None,
            }

        if len(reset_request.new_password) < 8:
            return {
                "success": False,
                "status": 400,
                "isActive": False,
                "message": "The new password must be at least 8 characters long.",
                "data": None,
            }

        user.set_password(reset_request.new_password)
        db.commit()

        logging.info("Password reset successfully for %s", user.email)
        return {
            "success": True,
            "status": 200,
            "isActive": (user.status == models.StatusEnum.active),
            "message": "Password reset successfully.",
            "data": None,
        }

    except Exception as e:
        logging.exception("Reset password error: %s", e)
        db.rollback()
        return {
            "success": False,
            "status": 500,
            "isActive": False,
            "message": "An unexpected error occurred. Please try again later.",
            "data": None,
        }
