from fastapi import APIRouter, Depends , HTTPException, status ,Query 
from typing import List 
from sqlalchemy.orm import Session
from . import schemas as employee_admin_schemas
from src.database import get_db
from src.routers.employees import models, schemas
from loguru import logger as logging
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from src.utils.jwt import get_email_from_token

# Defining the router
router = APIRouter(
    prefix="/api/admin/employees",
    tags=["Admin"],
    responses={404: {"description": "Not found"}},
)


@router.get("/list")
def employees_list(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=100),   # 🔹 default 10, max 100
    offset: int = Query(0, ge=0),           # 🔹 default 0
):
    """
    Retrieve a list of all active employees.
    Only accessible by users with the 'superadmin' or 'admin' role.
    """

    try:
        # 🔹 Decode email from token
        try:
            email = get_email_from_token(token)
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Token decoding failed: {e}")
            return {
                "success": False,
                "status": status.HTTP_401_UNAUTHORIZED,
                "message": "Invalid or expired token",
                "data": None,
            }

        # 🔹 Fetch requesting user
        user = db.query(models.Employee).filter(models.Employee.email == email).first()
        if not user:
            logging.warning("User not found for email: %s", email)
            return {
                "success": False,
                "status": status.HTTP_404_NOT_FOUND,
                "message": "User not found",
                "data": None,
            }

        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        logging.info("User %s with role %s is accessing employees_list", email, role)

        # 🔹 Role check
        if role.lower() not in ("superadmin", "admin"):
            logging.warning(f"Unauthorized access attempt by {email} with role {role}")
            return {
                "success": False,
                "status": status.HTTP_403_FORBIDDEN,
                "message": "You do not have permission to access this resource",
                "data": None,
            }

        # 🔹 Fetch employees with status = active
        query = (
            db.query(models.Employee)
            .filter(models.Employee.status.in_([models.StatusEnum.active, models.StatusEnum.inactive]))
            .order_by(models.Employee.created_at.desc())  # newest first
        )
        total = query.count()  # total before pagination

        employees = query.offset(offset).limit(limit).all()
        
        if not employees:
            return {
                "success": True,
                "status": status.HTTP_200_OK,
                "message": "No active employees found",
                "data": [],
                "pagination": {
                    "total": total,
                    "limit": limit,
                    "offset": offset,
            },
            }

        logging.info("Admin %s retrieved %d employees", email, len(employees))

        data = [
            schemas.EmployeeData(
                id=e.id,
                email=e.email,
                role=e.role.value if hasattr(e.role, "value") else str(e.role),
                status=e.status.value if hasattr(e.status, "value") else str(e.status),
                created_at=e.created_at,
                updated_at=e.updated_at,
                profile=schemas.EmployeeProfileData.from_orm(e.profile) if e.profile else None,
            )
            for e in employees
        ]

        return {
            "success": True,
            "status": status.HTTP_200_OK,
            "message": "Active employees retrieved successfully",
            "data": data,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_next": offset + limit < total,
                "has_prev": offset > 0,
            },
        }

    except Exception as e:
        logging.exception("Unexpected error in employees_list: %s", e)
        return {
            "success": False,
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "message": "An unexpected error occurred while fetching employees. Please try again later.",
            "data": None,
        }

@router.put("/update/{employee_id}", response_model=schemas.EmployeeData)
def update_employee_info(
    employee_id: int,
    payload: employee_admin_schemas.UpdateEmployeeSchema,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    """
    Update employee details (status, role, profile info).
    Only accessible by users with the 'admin' role.
    """

    # ----------------------------
    # 🔹 Decode token and fetch user
    # ----------------------------
    try:
        email = get_email_from_token(token)
    except HTTPException:
        raise
    except Exception as e:
        logging.error("Token decoding failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(models.Employee).filter(models.Employee.email == email).first()
    if not user:
        logging.warning("Token user not found in DB: %s", email)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authenticated user not found",
        )

    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    logging.info("Authenticated user %s with role %s accessing update_employee_info", email, role)

    # ----------------------------
    # 🔹 Authorization check
    # ----------------------------
    if role.lower() != "superadmin":
        logging.warning("Unauthorized update attempt by %s with role %s", email, role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update employee info",
        )

    # ----------------------------
    # 🔹 Fetch target employee
    # ----------------------------
    employee = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
    if not employee:
        logging.warning("Employee not found with ID %d (requested by %s)", employee_id, email)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target employee not found",
        )

    # ----------------------------
    # 🔹 Update employee fields
    # ----------------------------
    if payload.status is not None:
        employee.status = payload.status
    if payload.role is not None:
        employee.role = payload.role

    # ----------------------------
    # 🔹 Update employee profile
    # ----------------------------
    profile = employee.profile
    if not profile:
        logging.warning("Employee %d has no profile to update", employee_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Employee profile not found",
        )

    # Map of payload fields → profile attributes
    profile_updates = {
        "first_name": payload.first_name,
        "last_name": payload.last_name,
        "phone_number": payload.phone_number,
        "address": payload.address,
        "state": payload.state,
        "country": payload.country,
        "pin_code": payload.pin_code,
        "state_name": getattr(payload, "state_name", None).lower() if getattr(payload, "state_name", None) else None,
        "pc_name": getattr(payload, "pc_name", None).lower() if getattr(payload, "pc_name", None) else None,
    }

    for field, value in profile_updates.items():
        if value is not None:
            setattr(profile, field, value)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logging.exception("Database commit failed while updating employee %d: %s", employee_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update employee info, please try again later",
        )

    db.refresh(employee)
    db.refresh(profile)

    logging.info("Employee %d updated successfully by admin %s", employee_id, email)

    # ----------------------------
    # 🔹 Return response
    # ----------------------------
    return schemas.EmployeeData(
        id=employee.id,
        email=employee.email,
        role=employee.role.value if hasattr(employee.role, "value") else str(employee.role),
        status=employee.status.value if hasattr(employee.status, "value") else str(employee.status),
        created_at=employee.created_at,
        updated_at=employee.updated_at,
        profile=schemas.EmployeeProfileData.from_orm(profile),
    )


@router.delete("/delete/{employee_id}")
def delete_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    """
    Soft delete an employee by setting their status to inactive.
    Only accessible by users with the 'superadmin' role.
    """

    try:
        # 🔹 Decode token
        try:
            email = get_email_from_token(token)
        except HTTPException:
            raise  # re-raise FastAPI's HTTPException
        except Exception as e:
            logging.error(f"Token decoding failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 🔹 Fetch authenticated user
        user = db.query(models.Employee).filter(models.Employee.email == email).first()
        if not user:
            logging.warning("Authenticated user not found in DB: %s", email)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Authenticated user not found",
            )

        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        logging.info("Authenticated user %s with role %s accessing delete_employee", email, role)

        # 🔹 Authorization: only superadmin
        if role.lower() != "superadmin":
            logging.warning("Unauthorized delete attempt by %s with role %s", email, role)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only superadmins can delete employees",
            )

        # 🔹 Prevent deleting yourself
        if user.id == employee_id:
            logging.warning("User %s attempted to delete themselves", email)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot delete your own account",
            )

        # 🔹 Fetch target employee
        employee = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
        if not employee:
            logging.warning("Target employee not found (id=%s)", employee_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found",
            )

        # 🔹 Soft delete
        if employee.status == models.StatusEnum.inactive:
            logging.info("Employee %s is already inactive", employee.email)
            return {
                "success": False,
                "status": 400,
                "message": f"Employee {employee.email} is already inactive",
                "data": None,
            }

        employee.status = models.StatusEnum.inactive
        db.commit()
        db.refresh(employee)

        logging.info("Soft-deleted employee %s (status=inactive)", employee.email)
        return {
            "success": True,
            "status": 200,
            "message": f"Employee {employee.email} has been marked as inactive",
            "data": {
                "id": employee.id,
                "email": employee.email,
                "status": employee.status.value,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Unexpected error in delete_employee: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting employee. Please try again later.",
        )
