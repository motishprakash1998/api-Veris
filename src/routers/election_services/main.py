import os
import uuid
import urllib.parse
from . import models
from . import schemas
from . import controller
from loguru import logger
from sqlalchemy import func
from dotenv import load_dotenv
from fastapi import Body,Query
from src.database import  get_db
from sqlalchemy.orm import Session
from datetime import timedelta,datetime
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from fastapi import APIRouter, Depends, HTTPException,status,Request
from fastapi.responses import JSONResponse
from typing import List, Optional, Any, Dict
from src.utils.jwt import get_email_from_token
from src.routers.employees import models as employee_models
from src.routers.employees import schemas as employee_schemas
load_dotenv ()

# Defining the router
router = APIRouter(
    prefix="/api/electionservices",
    tags=["Election Services"],
    responses={404: {"description": "Not found"}},
)

# Define the API endpoints Request and Response models for Fetch Election Services data from the database

# NOTE: I removed the strict response_model so the endpoint can return either the
# legacy {total, items} shape or the new professional "details" object.
# If you want strict typing, re-add response_model=schemas.ElectionServicesResponse
# and convert controller output to match that schema before returning.

class _DictPayloadWrapper:
    """Tiny wrapper so controller can call payload.dict(exclude_unset=True)."""
    def __init__(self, data: Dict):
        self._data = data

    def dict(self, exclude_unset: bool = True) -> Dict:
        # ignore exclude_unset because we already prepared data accordingly
        return self._data

def to_title(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value.title()  # converts to Title Caps
    return value


@router.post("/create_by_candidate")
def create_candidate_endpoint(
    payload: schemas.ElectionUpdateSchema,   # use/create a dedicated Create schema if you want
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> Any:
    """
    Create a new election result entry (with related state/pc/party/candidate/election as needed).
    - Admin/Superadmin: unrestricted
    - Employee: allowed only if payload.state_name & pc_name match their profile
    """
    try:
        # normalize incoming validated payload to lowercase (we will still rely on controller but double-check)
        data = payload.dict(exclude_unset=True)
        normalized = {}
        for k, v in data.items():
            if isinstance(v, str):
                normalized[k] = v.strip().lower()
            else:
                normalized[k] = v
        # wrap so controller can call .dict()
        class _P:
            def __init__(self, d): self._d = d
            def dict(self, exclude_unset=True): return self._d

        wrapped = _P(normalized)

        # auth
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        role = user.role.value if hasattr(user.role, "value") else str(user.role)

        # employee-scoped check
        if role.lower() == "employee":
            profile = (
                db.query(employee_models.EmployeeProfile)
                .filter(employee_models.EmployeeProfile.employee_id == user.id)
                .first()
            )
            if not profile:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not assigned any state/constituency.",
                )

            # require payload to include state_name & pc_name
            payload_state = normalized.get("state_name")
            payload_pc = normalized.get("pc_name")
            if not payload_state or not payload_pc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Employee must provide state_name and pc_name that match their profile."
                )

            if payload_state != (profile.state_name or "").strip().lower() or payload_pc != (profile.pc_name or "").strip().lower():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only create records for your assigned state/constituency.",
                )

        elif role.lower() not in ["superadmin", "admin"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized role.")

        # create
        created = controller.create_candidate_entry(db=db, payload=wrapped)

        return {
            "success": True,
            "status": status.HTTP_201_CREATED,
            "message": "Created candidate election entry successfully",
            "data": created,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unhandled exception while creating candidate entry")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "status_code": 500,
                "message": "An unexpected error occurred while creating.",
                "data": {"error": str(exc)},
            },
        )

@router.get("/fetch_data")
def fetch_election_data(
    filters: schemas.ElectionFilters = Depends(),  # ✅ schema for query params
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> Any:
    """
    Fetch election data with role-based restrictions:
    - superadmin/admin → unrestricted (all data if no filters)
    - employee → only data from assigned state_name/pc_name
    """

    try:
        # 🔹 Decode email from token
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

        # 🔹 Fetch user
        user = (
            db.query(employee_models.Employee)
            .filter(employee_models.Employee.email == email)
            .first()
        )
        if not user:
            logger.warning("User not found for email: %s", email)
            return {
                "success": False,
                "status": status.HTTP_404_NOT_FOUND,
                "message": "User not found",
                "data": None,
            }

        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        logger.info("User %s with role %s is accessing election data", email, role)

        # -----------------------------
        # 🔹 Role-based restrictions
        # -----------------------------
        if role.lower() in ["superadmin", "admin"]:
            # Unrestricted – use filters directly
            allowed_state = filters.state_name
            allowed_pc = filters.pc_name

        elif role.lower() == "employee":
            # Restrict to assigned profile
            profile = (
                db.query(employee_models.EmployeeProfile)
                .filter(employee_models.EmployeeProfile.employee_id == user.id)
                .first()
            )

            if not profile or (not profile.state_name and not profile.pc_name):
                return {
                    "success": False,
                    "status": status.HTTP_403_FORBIDDEN,
                    "message": "You are not assigned any state or constituency. Please contact support.",
                    "data": None,
                }

            # if employee provided filters, ignore them → force assigned ones
            allowed_state = profile.state_name
            allowed_pc = profile.pc_name

        else:
            return {
                "success": False,
                "status": status.HTTP_403_FORBIDDEN,
                "message": "Unauthorized role. Please contact support.",
                "data": None,
            }

        # -----------------------------
        # 🔹 Call controller
        # -----------------------------
        result = controller.get_election_services(
            db=db,
            pc_name=allowed_pc,
            state_name=allowed_state,
            categories=filters.categories,
            party_name=filters.party_name,
            party_symbol=filters.party_symbol,
            sex=filters.sex,
            min_age=filters.min_age,
            max_age=filters.max_age,
            limit=filters.limit,
        )

        # -----------------------------
        # 🔹 Format response
        # -----------------------------
        if isinstance(result, dict) and "details" in result:
            data = result["details"]["data"]
            if "items" in data:
                formatted_items = []
                for item in data["items"]:
                    formatted_items.append({
                        **item,
                        "state_name": to_title(item.get("state_name")),
                        "pc_name": to_title(item.get("pc_name")),
                        "candidate_name": to_title(item.get("candidate_name")),
                        "party_name": to_title(item.get("party_name")),
                        "party_symbol": to_title(item.get("party_symbol")),
                        "category": to_title(item.get("category")),
                        "sex": to_title(item.get("sex")),
                    })
                data["items"] = formatted_items
            return result


        if isinstance(result, dict) and "details" in result:
            return result

        logger.warning("Controller returned unexpected shape")
        return result

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unhandled exception while fetching election services")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "status_code": 500,
                "message": "An unexpected error occurred while processing your request.",
                "data": {"error": str(exc)},
            },
        )
        
# Create a route to get election information by ID (no role checks)
@router.get("/get_candidate_info/{candidate_id}")
def get_candidate_data_by_id(
    candidate_id: int,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> Any:
    """
    Get election data by Candidate ID.
    """

    try:
        # 🔹 Decode user from token
        try:
            email = get_email_from_token(token)
        except Exception as e:
            logger.error(f"Token decoding failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # 🔹 Fetch user
        user = db.query(employee_models.Employee).filter(
            employee_models.Employee.email == email
        ).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        logger.info("User %s with role %s is accessing candidate data by ID", email, role)
        # -----------------------------
        
        # 🔹 Fetch candidate record (returns list of dicts now)
        candidate_record = controller.get_candidate_details_by_id(db, candidate_id)
        if not candidate_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate record not found",
            )

        # 🔹 Return record directly
        return {
            "success": True,
            "status": status.HTTP_200_OK,
            "message": "Candidate record fetched successfully",
            "data": candidate_record,   # already JSON serializable
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unhandled exception while fetching candidate record by ID")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "status_code": 500,
                "message": "An unexpected error occurred while fetching the record.",
                "data": {"error": str(exc)},
            },
        )
        
  
@router.put("/update_by_candidate/{candidate_id}")
def update_candidate_data(
    candidate_id: int,
    payload: schemas.ElectionUpdateSchema,
    db: Session = Depends(get_db),
) -> Any:
    try:
        # --- 1) get provided fields as dict (only set fields)
        data = payload.dict(exclude_unset=True)

        # --- 2) lowercase all string values (you can customize allowed fields if needed)
        normalized = {}
        for k, v in data.items():
            if isinstance(v, str):
                normalized[k] = v.strip().lower()
            else:
                normalized[k] = v

        # --- 3) pass wrapped payload to controller (controller expects .dict())
        wrapped_payload = _DictPayloadWrapper(normalized)

        updated = controller.update_election_service_by_candidate(
            db=db,
            candidate_id=candidate_id,
            payload=wrapped_payload,
            election_id=None,      # or set if you want to target a specific election
            update_all=False,      # set True if you want to update all results
        )

        return {
            "success": True,
            "status": status.HTTP_200_OK,
            "message": "Candidate election record updated successfully",
            "data": updated,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unhandled exception while updating candidate record")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "status_code": 500,
                "message": "An unexpected error occurred while updating.",
                "data": {"error": str(exc)},
            },
        )
        

@router.delete("/delete_by_candidate/{candidate_id}")
def soft_delete_candidate_record(
    candidate_id: int,
    result_id: Optional[int] = None,
    delete_all: Optional[bool] = False,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> Any:
    """
    Soft-delete candidate result(s).
    - candidate_id: path param
    - result_id: optional query param to delete (mark) a specific result
    - delete_all: optional query flag; if true marks all results for the candidate
    Authorization: only superadmin/admin allowed.
    """

    try:
        # decode token
        try:
            email = get_email_from_token(token)
        except Exception as e:
            logger.error("Token decoding failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # fetch user
        user = db.query(employee_models.Employee).filter(
            employee_models.Employee.email == email
        ).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        role = user.role.value if hasattr(user.role, "value") else str(user.role)

        # Only allow admins/superadmins to soft-delete
        if role.lower() not in ["superadmin", "admin"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to delete (soft-delete) records.",
            )

        # perform soft-delete
        marked = controller.delete_candidate_results(
            db=db,
            candidate_id=candidate_id,
            result_id=result_id,
            delete_all=bool(delete_all),
        )

        return {
            "success": True,
            "status": status.HTTP_200_OK,
            "message": "Marked candidate result(s) as deleted successfully",
            "data": marked,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unhandled exception while soft-deleting candidate record")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "status_code": 500,
                "message": "An unexpected error occurred while deleting.",
                "data": {"error": str(exc)},
            },
        )