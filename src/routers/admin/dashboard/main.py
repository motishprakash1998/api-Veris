from fastapi import APIRouter, Depends , HTTPException, status
from typing import List 
from sqlalchemy.orm import Session ,Query
from . import schemas
from src.database import get_db
# from src.routers.employees import models, schemas
from loguru import logger
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from src.utils.jwt import get_email_from_token
# from . import  controllers
from src.routers.admin.dashboard import  controllers
from src.routers.employees import models as employee_models
# from . import controllers
# Defining the router
router = APIRouter(
    prefix="/api/admin/dashboard",
    tags=["Admin Dashboard"],
    responses={404: {"description": "Not found"}},
)

@router.get("/dashboard")
def dashboard(
    filters: schemas.CommonFilters = Depends(),
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    """
    Dashboard-style API that returns data based on role:
    - Employee → restricted to assigned state/pc
    - Admin / Superadmin → full ECI data
    """

    # -----------------------------
    # Decode token & get user
    # -----------------------------
    try:
        email = get_email_from_token(token)
    except Exception as e:
        logger.error("Token decoding failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(employee_models.Employee).filter(
        employee_models.Employee.email == email
    ).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if role.lower() not in ["superadmin", "admin", "employee"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized role."
        )

    # -----------------------------
    # Employee restrictions
    # -----------------------------
    assigned_state = assigned_pc = None
    if role.lower() == "employee":
        profile = db.query(employee_models.EmployeeProfile).filter(
            employee_models.EmployeeProfile.employee_id == user.id
        ).first()

        assigned_state = (profile.state_name or "").strip().lower() if profile else None
        assigned_pc = (profile.pc_name or "").strip().lower() if profile else None

        if not assigned_state and not assigned_pc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not assigned any state or constituency. Please contact support.",
            )
        # 🔥 Override filters for employee
        filters.state_name = assigned_state
        filters.pc_name = assigned_pc
    # -----------------------------
    # Fetch dashboard data based on role
    # -----------------------------
    try:
        # Admin / Superadmin → ECI Data
        data = controllers.get_dashboard_data(db, filters,role)
    except Exception as e:
       logger.error(f"Error in geting the data.")
    try:
        dashboard_response_data = {
        "success": True,
        "status": 200,
        "message": "Dashboard data fetched.",
        "data": data,
        }

        return dashboard_response_data
    except Exception as e:
        return {
        "success": False,
        "status": 200,
        "message": "Dashboard data Not fetched.",
        "data": None,
        }
