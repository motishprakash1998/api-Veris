# src/employee/routes/waiting.py

import logging
from . import  schemas as waiting_schemas
from loguru import logger
from src.database import get_db
from typing import List, Optional
from sqlalchemy.orm import Session 
from src.routers.employees import models, schemas
from fastapi import APIRouter, Depends, HTTPException, status,BackgroundTasks,Query
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
from src.utils.jwt import get_email_from_token
from sqlalchemy import or_ , func ,String
from src.utils.email_service import send_status_update_email


logger = logging.getLogger(__name__)

# Defining the router
router = APIRouter(
    prefix="/api/admin/waiting",
    tags=["Waiting Users"],
    responses={404: {"description": "Not found"}},
)

@router.get("/list")
def waiting_list(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
    limit: int = Query(10, ge=1, le=100, description="Number of records per page"),
    offset: int = Query(0, ge=0, description="Starting index for pagination"),
    name: Optional[str] = Query(None, description="Filter by employee name or email"),
    state_name: Optional[str] = Query(None, description="Filter by state_name (string match)"),
    pc_name: Optional[str] = Query(None, description="Filter by PC/Constituency name"),
):
    """List waiting employees with pagination + filters. Only accessible by admin/superadmin."""

    try:
        # 🔹 Decode token
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

        # 🔹 Fetch requesting user
        user = db.query(models.Employee).filter(models.Employee.email == email).first()
        if not user:
            logging.warning("Authenticated user not found: %s", email)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Authenticated user not found",
            )

        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        logging.info("User %s with role %s accessing waiting_list", email, role)

        # 🔹 Only admin/superadmin can access
        if role.lower() not in ["admin", "superadmin"]:
            logging.warning("Unauthorized waiting_list access attempt by %s with role %s", email, role)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to view waiting employees",
            )

        # 🔹 Base query
        query = db.query(models.Employee).filter(models.Employee.status == models.StatusEnum.waiting)

        # -------------------- ✅ Apply Filters --------------------
        if name:
            query = query.filter(
                or_(
                    models.Employee.email.ilike(f"%{name}%"),
                    models.Employee.profile.has(models.EmployeeProfile.first_name.ilike(f"%{name}%")),
                )
            )

        if state_name:
            query = query.join(models.Employee.profile).filter(func.lower(models.EmployeeProfile.state_name.cast(String)) == state_name.lower())

        if pc_name:
            query = query.join(models.Employee.profile).filter(
                models.EmployeeProfile.pc_name.ilike(f"%{pc_name}%")
            )
        # ----------------------------------------------------------

        total = query.count()
        employees = query.order_by(models.Employee.created_at.desc()).offset(offset).limit(limit).all()

        if not employees:
            return {
                "success": True,
                "status": 200,
                "message": "No employees found with given filters",
                "data": [],
                "pagination": {
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "has_next": offset + limit < total,
                    "has_prev": offset > 0,
                },
            }

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
            "status": 200,
            "message": "Employees retrieved successfully",
            "data": data,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_next": offset + limit < total,
                "has_prev": offset > 0,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Unexpected error in waiting_list: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching waiting employees. Please try again later.",
        )

    
@router.put("/update/{employee_id}", response_model=schemas.EmployeeData)
def update_permission(
    employee_id: int,
    payload: waiting_schemas.UpdatePermissionSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    """
    Approve or reject a waiting employee.
    Only accessible by admin/superadmin.
    Updates state_name and pc_name in the employee profile if provided.
    """

    try:
        # 🔹 Decode token
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

        # 🔹 Fetch authenticated user
        user = db.query(models.Employee).filter(models.Employee.email == email).first()
        if not user:
            logging.warning("Authenticated user not found: %s", email)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Authenticated user not found",
            )

        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        logging.info("User %s with role %s is accessing update_permission", email, role)

        if role.lower() not in ["admin", "superadmin"]:
            logging.warning("Unauthorized update_permission attempt by %s with role %s", email, role)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update employee permissions",
            )

        # 🔹 Fetch target employee
        employee = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")

        if employee.status != models.StatusEnum.waiting:
            raise HTTPException(
                status_code=400,
                detail="Only waiting employees can be approved or rejected",
            )

        # 🔹 Approve or reject
        employee.status = models.StatusEnum.active if payload.approve else models.StatusEnum.inactive
        if payload.role:
            employee.role = payload.role

        # 🔹 Update profile info
        profile = employee.profile
        if payload.state:
            profile.state = payload.state
        if payload.country:
            profile.country = payload.country
        if payload.pin_code:
            profile.pin_code = payload.pin_code
        if payload.state_name:
            profile.state_name = payload.state_name.lower()
        if payload.pc_name:
            profile.pc_name = payload.pc_name.lower()

        db.commit()
        db.refresh(employee)
        db.refresh(profile)

        logging.info(
            "Employee %s permission updated by %s (new status=%s, new role=%s)",
            employee.email,
            email,
            employee.status.value,
            employee.role.value if hasattr(employee.role, "value") else str(employee.role),
        )
         # ✅ Background email send
        background_tasks.add_task(
            send_status_update_email,
            to_email=employee.email,
            full_name=employee.profile.first_name if employee.profile and employee.profile.first_name else employee.email,
            approved=(employee.status == models.StatusEnum.active),
            state_name=profile.state_name,
            pc_name=profile.pc_name,
        )
        return schemas.EmployeeData(
            id=employee.id,
            email=employee.email,
            role=employee.role.value if hasattr(employee.role, "value") else str(employee.role),
            status=employee.status.value if hasattr(employee.status, "value") else str(employee.status),
            created_at=employee.created_at,
            updated_at=employee.updated_at,
            profile=schemas.EmployeeProfileData.from_orm(profile),
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Unexpected error in update_permission: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating employee permission. Please try again later.",
        )
        
@router.delete("/delete/{employee_id}")
def delete_waiting_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    """
    Soft delete a waiting employee → mark as inactive.
    Only accessible by admin/superadmin.
    """

    try:
        # 🔹 Decode token
        try:
            email = get_email_from_token(token)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Token decoding failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 🔹 Fetch authenticated user
        user = db.query(models.Employee).filter(models.Employee.email == email).first()
        if not user:
            logger.warning(f"Authenticated user not found: {email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Authenticated user not found",
            )

        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        logger.info(f"User {email} with role {role} attempting to delete waiting employee")

        if role.lower() not in ["admin", "superadmin"]:
            logger.warning(f"Unauthorized delete_waiting attempt by {email} with role {role}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete waiting employees",
            )

        # 🔹 Fetch target employee
        employee = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
        if not employee:
            return {
                "success": False,
                "status": 404,
                "message": "Employee not found",
                "data": None,
            }

        if employee.status != models.StatusEnum.waiting:
            return {
                "success": False,
                "status": 400,
                "message": "Only waiting employees can be deleted",
                "data": {
                    "id": employee.id,
                    "email": employee.email,
                    "status": employee.status.value,
                },
            }

        # 🔹 Soft delete → mark inactive
        employee.status = models.StatusEnum.inactive
        db.commit()
        db.refresh(employee)

        logger.info(f"Waiting employee {employee.email} soft deleted (inactive)")

        return {
            "success": True,
            "status": 200,
            "message": f"Waiting employee {employee.email} marked as inactive",
            "data": {
                "id": employee.id,
                "email": employee.email,
                "status": employee.status.value,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error in delete_waiting_employee: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting employee. Please try again later.",
        )
