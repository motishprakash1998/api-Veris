import os
import  boto3
import uuid
import urllib.parse
from . import models
from . import schemas
from . import controller
from sqlalchemy import func
from dotenv import load_dotenv
from src.database import  get_db
from sqlalchemy.orm import Session
from loguru import logger as logging
from datetime import timedelta,datetime
from fastapi import Body,Query,UploadFile ,File
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from src.routers.employees.schemas import LoginSchema, TokenResponse
from fastapi import APIRouter, Depends, HTTPException,status,Request
from src.utils.jwt import create_access_token, get_email_from_token,create_refresh_token,verify_password
from fastapi.responses import JSONResponse
from fastapi import BackgroundTasks

load_dotenv ()

# Defining the router
router = APIRouter(
    prefix="/api/employee",
    tags=["Employees"],
    responses={404: {"description": "Not found"}},
)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}

@router.post("/login", response_model=TokenResponse)
def login(employee_credentials: LoginSchema = Body(...), db: Session = Depends(get_db)):
    logging.debug("Login function called")

    try:
        logging.info("Login attempt for email: %s", employee_credentials.email)

        employee = (
            db.query(
                models.Employee.id,
                models.Employee.email,
                models.Employee.password_hash,
                models.Employee.role,
                models.Employee.status,  # Enum field
            )
            .filter(models.Employee.email == employee_credentials.email)
            .first()
        )

        if not employee:
            logging.warning("Login failed: email not found: %s", employee_credentials.email)
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "status": 401,
                    "isActive": False,
                    "message": "The email you entered does not match any account. Please check and try again.",
                    "data": None,
                },
            )

        logging.debug(f"Employee found: {employee.email} || Status: {employee.status}")

        # 🔹 Extract enum value safely
        status_val = getattr(employee.status, "value", str(employee.status))

        # 🔹 Check account status before verifying password
        if status_val == "waiting":
            logging.info("Login blocked: account under review for %s", employee.email)
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "status": 403,
                    "isActive": False,
                    "message": "Your request is under review, please wait for approval.",
                    "data": None,
                },
            )

        if status_val != "active":
            logging.warning("Login blocked: inactive account for %s", employee.email)
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "status": 403,
                    "isActive": False,
                    "message": "Your account is not active. Please contact support.",
                    "data": None,
                },
            )

        # ✅ Now verify password
        if not verify_password(employee_credentials.password, employee.password_hash):
            logging.warning("Login failed: bad password for %s", employee_credentials.email)
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "status": 401,
                    "isActive": False,
                    "message": "The password you entered is incorrect. Please try again.",
                    "data": None,
                },
            )

        # Make role JSON-serializable
        role_obj = employee.role
        role_str = getattr(role_obj, "value", None) or getattr(role_obj, "name", None) or str(role_obj)

        access_token = create_access_token(data={"sub": employee.email, "role": role_str})
        refresh_token = create_refresh_token(data={"sub": employee.email, "role": role_str})

        logging.info("User %s logged in successfully", employee.email)

        return {
            "success": True,
            "status": 200,
            "isActive": True,
            "message": "Login successful. Welcome back!",
            "data": {
                "email_id": employee.email,
                "role":role_str,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
            },
        }

    except Exception as e:
        logging.exception("An error occurred during login: %s", e)
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

@router.get("/info", response_model=schemas.EmployeeResponse)
def get_info(request: Request, db: Session = Depends(get_db),
             token : str = Depends(oauth2_scheme)):
    """
    Endpoint to fetch employee information using the JWT token.
    """
    try:
        # -------------------------
        # Extract & validate token
        # -------------------------
        token = request.headers.get("Authorization")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token is missing",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not token.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token format. Token must start with 'Bearer'.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = token.split(" ")[1]

        # -------------------------
        # Decode token → email
        # -------------------------
        email = get_email_from_token(token)

        # -------------------------
        # Fetch employee
        # -------------------------
        employee = db.query(models.Employee).filter(models.Employee.email == email).first()
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found. Please ensure the token is valid.",
            )

        if employee.status != models.StatusEnum.active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is inactive. Please contact support.",
            )

        # -------------------------
        # Fetch employee profile
        # -------------------------
        profile = db.query(models.EmployeeProfile).filter(
            models.EmployeeProfile.employee_id == employee.id
        ).first()

        # -------------------------
        # Build response data
        # -------------------------
        role_value = employee.role.value if isinstance(employee.role, models.RoleEnum) else employee.role
        logging.info(f"Employee role for {employee.email}: {role_value}")

        employee_data = schemas.EmployeeData(
            id=employee.id,
            email=employee.email,
            role=employee.role,
            status=employee.status,
            first_name=profile.first_name if profile else None,
            last_name=profile.last_name if profile else None,
            phone_number=profile.phone_number if profile else None,
            profile_path=profile.profile_path if profile else "profile_pictures/default.png",
            date_of_birth=profile.date_of_birth if profile else None,
            gender=profile.gender.value if profile and profile.gender else None,
            address=profile.address if profile else None,
            state=profile.state if profile else None,
            country=profile.country if profile else None,
            pin_code=profile.pin_code if profile else None,
            state_name=profile.state_name if profile else None,
            pc_name=profile.pc_name if profile else None,
            emergency_contact=profile.emergency_contact if profile else None,
            profile_completed=1 if profile and profile.profile_completed else 0,
            created_at=employee.created_at,
            updated_at=employee.updated_at,
        )

        return schemas.EmployeeResponse(
            success=True,
            status=200,
            isActive=employee.status == models.StatusEnum.active,
            message="Employee found successfully",
            data=employee_data,
        )

    except HTTPException:
        raise

    except Exception as e:
        logging.error(f"Unexpected error in /info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )

@router.post("/create", response_model=schemas.TokenResponse, status_code=status.HTTP_201_CREATED)
def create(background_tasks: BackgroundTasks, payload: schemas.CreateEmployeeSchema, db: Session = Depends(get_db)):
    try:
        logging.info(f"Employee creation attempt for email: {payload.email}")

        # --- Check if employee already exists ---
        existing = (
            db.query(models.Employee)
              .filter(func.lower(models.Employee.email) == func.lower(payload.email))
              .first()
        )
        if existing:
            logging.warning(f"Employee creation failed: Email {payload.email} already exists")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email already exists. Please use a different email.",
            )

        # --- Split full name ---
        name_parts = payload.full_name.strip().split(maxsplit=1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        # --- Create Employee object ---
        new_employee = models.Employee(
            email=payload.email,
            role=models.RoleEnum.employee,
            status=models.StatusEnum.waiting,   # pending approval
        )
        new_employee.set_password(payload.password)

        # --- Create Profile object ---
        profile = models.EmployeeProfile(
            employee=new_employee,
            first_name=first_name,
            last_name=last_name,
            phone_number=payload.phone_number,
            profile_path="profile_pictures/default.png",
            profile_completed=False,
        )

        # --- Add to session ---
        db.add(new_employee)
        db.add(profile)

        # --- Commit & refresh to populate timestamps & IDs ---
        try:
            db.commit()
            db.refresh(new_employee)
            db.refresh(profile)
        except Exception:
            db.rollback()
            logging.exception("Database commit failed during employee creation")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred while creating the employee. Please try again.",
            )

        # --- Send mail in background (after commit so no rollback issues) ---
        from src.utils.email_service import send_account_creation_email
        background_tasks.add_task(
            send_account_creation_email, new_employee.email, f"{first_name} {last_name}"
        )

        # --- Build profile schema AFTER refresh ---
        profile_payload = {
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "phone_number": profile.phone_number,
            "date_of_birth": profile.date_of_birth,
            "gender": (profile.gender.value if hasattr(profile, "gender") and profile.gender else profile.gender),
            "address": profile.address,
            "state": profile.state,
            "country": profile.country,
            "pin_code": profile.pin_code,
            "profile_path": profile.profile_path,
            "emergency_contact": profile.emergency_contact,
            "profile_completed": bool(profile.profile_completed),
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
            "state_name": getattr(profile, "state_name", None),
            "pc_name": getattr(profile, "pc_name", None),
        }
        profile_data = schemas.EmployeeProfileData(**profile_payload)

        employee_data = schemas.EmployeeData(
            id=new_employee.id,
            email=new_employee.email,
            role=new_employee.role.value,
            status=new_employee.status.value,
            created_at=new_employee.created_at,
            updated_at=new_employee.updated_at,
            profile=profile_data,
        )

        logging.info(f"Employee {new_employee.email} created successfully with role '{new_employee.role.value}'")

        # --- Response ---
        if new_employee.status == models.StatusEnum.active:
            access_token = create_access_token(
                data={"sub": new_employee.email, "role": new_employee.role.value}
            )
            return schemas.TokenResponse(
                success=True,
                status=status.HTTP_201_CREATED,
                isActive=True,
                isWaiting=False,
                message="Employee account created and activated successfully.",
                data={
                    "employee": employee_data.model_dump(),
                    "access_token": access_token,
                    "token_type": "bearer",
                },
            )
        else:
            return schemas.TokenResponse(
                success=True,
                status=status.HTTP_201_CREATED,
                isActive=False,
                isWaiting=True,
                message="Employee account created successfully and is pending admin approval.",
                data={"employee": employee_data.model_dump()},
            )

    except HTTPException:
        db.rollback()  # rollback if commit not done yet
        raise
    except Exception as e:
        logging.exception(f"Unexpected error during employee creation: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )

@router.get("/get-profile-path", response_model=schemas.EmployeeProfilePathResponse)
def get_profile_path(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """
    Get the employee's profile path from the database and return a public URL.
    Token is decoded to obtain email; EmployeeProfile is joined with Employee.
    """
    try:
        # Decode email from the token
        try:
            email = get_email_from_token(token)
        except HTTPException:
            # let downstream HTTPExceptions pass through
            raise
        except Exception as e:
            logging.error(f"Token decoding failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Fetch the EmployeeProfile by joining Employee (email -> employee)
        profile = (
            db.query(models.EmployeeProfile)
            .join(models.Employee, models.EmployeeProfile.employee_id == models.Employee.id)
            .filter(func.lower(models.Employee.email) == (email or "").lower())
            .first()
        )

        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee profile not found. Ensure the token is valid and try again.",
            )

        # profile_path (fallback to default if empty/None)
        profile_path = profile.profile_path or "profile_pictures/default.png"
        logging.info(f"Found profile path for employee_id={profile.employee_id}: {profile_path}")
    
        # Build public URL using Source bucket name  env var (fallback to requestable domain if not present)
        source_bucket_name = os.environ.get("SOURCE_BUCKET_NAME")
        if not source_bucket_name:
            logging.warning("DOMAIN env var not set; returning path without domain")
            public_url = profile_path
        else:
            # ensure path is URL-encoded
            encoded_path = urllib.parse.quote(profile_path.lstrip("/"))
            public_url = controller.generate_presigned_url(source_bucket_name, profile_path)

        return schemas.EmployeeProfilePathResponse(
            success=True,
            status=200,
            message="Employee profile path fetched successfully.",
            data={
                "profile_path": profile_path,
                "public_url": public_url,
            },
        )

    except HTTPException as http_exc:
        logging.warning(f"HTTP exception in get_user_profile_path: {http_exc.detail}")
        raise http_exc

    except Exception as e:
        logging.exception(f"Unexpected error in get_user_profile_path: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )
  
@router.put("/update-profile-path", response_model=schemas.EmployeeResponse)
async def update_profile_path(
    profile_picture: UploadFile = File(...),
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """
    Upload the profile picture to S3 and update the employee's profile_path.
    """
    try:
        # decode email from token
        try:
            email = get_email_from_token(token)
            if not email:
                raise ValueError("Empty email in token")
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Token decoding failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # fetch employee (case-insensitive)
        employee = (
            db.query(models.Employee)
            .filter(func.lower(models.Employee.email) == (email or "").lower())
            .first()
        )
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found. Ensure the token is valid and try again.",
            )

        # fetch profile (1:1)
        profile = (
            db.query(models.EmployeeProfile)
            .filter(models.EmployeeProfile.employee_id == employee.id)
            .first()
        )
        if not profile:
            # safer to require a profile to exist before setting path
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee profile not found. Please create a profile before uploading a picture.",
            )

        # validate file type
        if profile_picture.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file type. Only JPEG and PNG are allowed.",
            )

        # prepare S3 client and keys
        bucket_name = os.environ.get("S3_BUCKET_NAME", "ai-interview-bot")
        region = os.environ.get("S3_REGION", "us-east-1")

        # create a unique filename to avoid collisions
        original_name = profile_picture.filename or "upload"
        _, ext = os.path.splitext(original_name)
        ext = ext.lower() if ext else ""
        unique_name = f"{uuid.uuid4().hex}{ext}"
        # keep key structure consistent with your model (no leading slash)
        file_key = f"profile_pictures/{employee.email}/{unique_name}"

        # Upload to S3
        try:
            s3_client = boto3.client("s3", region_name=region)
            file_bytes = await profile_picture.read()
            s3_client.put_object(
                Bucket=bucket_name,
                Key=file_key,
                Body=file_bytes,
                ContentType=profile_picture.content_type,
            )
            logging.info(f"Uploaded profile picture to S3: s3://{bucket_name}/{file_key}")
        except Exception as s3_err:
            logging.exception("Error uploading file to S3")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload the profile picture to S3. Please try again.",
            )

        # Store the S3 key/path in profile.profile_path (keep stored value as the key so retrieval logic can decide)
        profile.profile_path = file_key

        # Commit changes
        try:
            db.add(profile)
            db.commit()
            # refresh both profile and employee to get updated timestamps if any
            db.refresh(profile)
            db.refresh(employee)
        except Exception as db_err:
            db.rollback()
            logging.exception("Database commit failed when updating profile_path")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred while updating the profile path. Please try again.",
            )

        # Convert profile_completed to int (schema expects 0/1)
        profile_completed_val = None
        if profile.profile_completed is not None:
            if isinstance(profile.profile_completed, bool):
                profile_completed_val = int(profile.profile_completed)
            else:
                try:
                    profile_completed_val = int(profile.profile_completed)
                except Exception:
                    profile_completed_val = 0

        # Return updated employee + profile data
        return schemas.EmployeeResponse(
            success=True,
            status=200,
            isActive=(employee.status == models.StatusEnum.active),
            message="Employee profile path updated successfully.",
            data=schemas.EmployeeData(
                id=employee.id,
                email=employee.email,
                role=employee.role.value if hasattr(employee.role, "value") else str(employee.role),
                status=employee.status.value if hasattr(employee.status, "value") else str(employee.status),
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
                profile_completed=profile_completed_val,
                created_at=employee.created_at,
                updated_at=employee.updated_at,
            ),
        )

    except HTTPException:
        raise

    except Exception as exc:
        logging.exception("Unexpected error in update_profile_path")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )

@router.put("/update-employee-info", response_model=schemas.EmployeeResponse)
def update_info(
    updated_info: schemas.EmployeeUpdateRequest = Body(...),
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """
    Update employee information.
    - Admins can update role.
    - Regular employees can update their profile fields.
    - Only doctors can update specialization, license number, years of experience (if you later add them back).
    - If all required fields are filled, profile_completed = True.
    """
    try:
        # ---------------------------
        # Decode employee email from token
        # ---------------------------
        try:
            email = get_email_from_token(token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # ---------------------------
        # Fetch employee & profile
        # ---------------------------
        employee = (
            db.query(models.Employee)
            .filter(models.Employee.email == email)
            .first()
        )
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found. Please ensure your token is valid.",
            )

        # Ensure profile exists
        if not employee.profile:
            employee.profile = models.EmployeeProfile(employee_id=employee.id)

        profile = employee.profile

        # ---------------------------
        # Validate and update fields
        # ---------------------------
        for field, value in updated_info.dict(exclude_unset=True).items():
            if field in [
                "first_name", "last_name", "phone_number", "profile_path", "address",
                "state", "country", "pin_code", "gender", "emergency_contact"
            ]:
                if not value or (isinstance(value, str) and not value.strip()):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"{field.replace('_', ' ').title()} cannot be empty.",
                    )
                if field in ["phone_number", "emergency_contact"]:
                    if not value.isdigit() or len(value) != 10:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"{field.replace('_', ' ').title()} must be a 10-digit number.",
                        )
                elif field == "gender":
                    allowed_genders = ["male", "female", "other"]
                    if value.lower() not in allowed_genders:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Gender must be one of: {', '.join(allowed_genders)}.",
                        )
                    value = value.lower()
                setattr(profile, field, value)

            elif field == "date_of_birth":
                try:
                    value = datetime.strptime(value, "%d/%m/%Y").date()
                    setattr(profile, field, value)
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid date format. Use DD/MM/YYYY.",
                    )

            elif field == "role":
                if employee.role != models.RoleEnum.superadmin:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Only admins can update roles.",
                    )
                setattr(employee, field, value)

            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Field '{field}' cannot be updated.",
                )

        # ---------------------------
        # Check profile completion
        # ---------------------------
        required_fields = [
            profile.first_name, profile.last_name, profile.phone_number,
            profile.profile_path, profile.address, profile.state,
            profile.country, profile.pin_code, profile.gender,
            profile.date_of_birth, profile.emergency_contact,
        ]

        profile.profile_completed = all(required_fields)

        # ---------------------------
        # Commit changes
        # ---------------------------
        try:
            db.commit()
            db.refresh(employee)
            db.refresh(profile)
        except Exception as e:
            db.rollback()
            logging.error(f"Update failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred while updating employee information.",
            )

        # ---------------------------
        # Response
        # ---------------------------
        return schemas.EmployeeResponse(
            success=True,
            status=200,
            isActive=employee.status == models.StatusEnum.active,
            message="Employee information updated successfully",
            data=schemas.EmployeeData.from_orm(employee),
        )

    except HTTPException as http_exc:
        raise http_exc

    except Exception as e:
        db.rollback()
        logging.error(f"Unexpected error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )

@router.post("/change-password", status_code=200)
def change_password(
    change_request: schemas.ChangePasswordSchema,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """
    Endpoint to change the password for the logged-in employee.
    """
    try:
        # -------------------------
        # Decode email from token
        # -------------------------
        try:
            email = get_email_from_token(token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # -------------------------
        # Fetch employee
        # -------------------------
        employee = db.query(models.Employee).filter(models.Employee.email == email).first()
        logging.debug(f"Password change attempt for employee: {employee}")

        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found. Ensure the token is valid and try again.",
            )

        # -------------------------
        # Verify old password
        # -------------------------
        if not employee.verify_password(change_request.old_password):
            logging.warning(f"Password change failed: Incorrect old password for {employee.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The old password is incorrect.",
            )

        # -------------------------
        # Validate new password
        # -------------------------
        if len(change_request.new_password) < 8:
            logging.warning(f"Weak new password attempt for {employee.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The new password must be at least 8 characters long.",
            )

        # -------------------------
        # Update password
        # -------------------------
        employee.set_password(change_request.new_password)
        db.commit()

        logging.info(f"Password changed successfully for {employee.email}")
        return {
            "success": True,
            "status": 200,
            "isActive": employee.status == models.StatusEnum.active,
            "message": "Password changed successfully.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error during password change: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )

@router.post("/forgot-password", status_code=200)
def forgot_password(forgot_request: schemas.ForgotPasswordSchema, db: Session = Depends(get_db)):
    """
    Endpoint to handle forgotten password by sending a reset link or token.
    """
    try:
        # -------------------------
        # Find employee by email
        # -------------------------
        employee = db.query(models.Employee).filter(models.Employee.email == forgot_request.email).first()
        if not employee:
            logging.warning(f"Forgot password: No employee found with {forgot_request.email}")
            return {
                "success": False,
                "status": 404,
                "isActive": False,
                "message": "No employee found with this email address.",
                "data": None,
            }

        # -------------------------
        # Generate reset token (1 hour expiry)
        # -------------------------
        reset_token = create_access_token(
            data={"sub": employee.email},
            expires_delta=timedelta(hours=1)
        )

        # -------------------------
        # Send reset token (email)
        # -------------------------
        controller.send_password_reset_email(email=employee.email, token=reset_token)

        logging.info(f"Password reset token sent to {employee.email}")
        return {
            "success": True,
            "status": 200,
            "isActive": employee.status == models.StatusEnum.active,
            "message": "A password reset link has been sent to your email.",
            "data": None,
        }

    except Exception as e:
        logging.error(f"Forgot password error: {e}")
        return {
            "success": False,
            "status": 500,
            "isActive": False,
            "message": "An unexpected error occurred. Please try again later.",
            "data": None,
        }


@router.post("/reset-password", status_code=200)
def reset_password(
    reset_request: schemas.ResetPasswordSchema,
    db: Session = Depends(get_db),
):
    """
    Endpoint to reset the password using a valid reset token.
    """
    try:
        # -------------------------
        # Decode & verify reset token
        # -------------------------
        token_data = controller.decode_access_token(reset_request.token)
        email = token_data.get("sub")  # JWT 'sub' holds email
        if not email:
            return {
                "success": False,
                "status": 400,
                "isActive": False,
                "message": "Invalid or expired token.",
                "data": None,
            }

        # -------------------------
        # Find employee
        # -------------------------
        employee = db.query(models.Employee).filter(models.Employee.email == email).first()
        if not employee:
            return {
                "success": False,
                "status": 404,
                "isActive": False,
                "message": "No employee found with this email address.",
                "data": None,
            }

        # -------------------------
        # Validate new password
        # -------------------------
        if len(reset_request.new_password) < 8:
            return {
                "success": False,
                "status": 400,
                "isActive": False,
                "message": "The new password must be at least 8 characters long.",
                "data": None,
            }

        # -------------------------
        # Update password
        # -------------------------
        employee.set_password(reset_request.new_password)
        db.commit()

        logging.info(f"Password reset successfully for {employee.email}")
        return {
            "success": True,
            "status": 200,
            "isActive": employee.status == models.StatusEnum.active,
            "message": "Password reset successfully.",
            "data": None,
        }

    except Exception as e:
        logging.error(f"Reset password error: {e}")
        db.rollback()
        return {
            "success": False,
            "status": 500,
            "isActive": False,
            "message": "An unexpected error occurred. Please try again later.",
            "data": None,
        }