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
from datetime import timedelta,datetime,timezone
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from fastapi import APIRouter, Depends, HTTPException,status,Request
from fastapi.responses import JSONResponse
from typing import List, Optional, Any, Dict,Tuple
from src.utils.jwt import get_email_from_token
from src.routers.employees import models as employee_models
from src.routers.employees import schemas as employee_schemas
from sqlalchemy.exc import IntegrityError
from src.routers.election_services.utilities import _to_dict
import re
from sqlalchemy.orm import load_only


# external libs: install them in your env
from rapidfuzz import fuzz
import phonetics

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
        # 🔹 Pagination Setup
        # -----------------------------
        limit = filters.limit or 10
        page = filters.page or 1
        offset = (page - 1) * limit
        # -----------------------------
        # 🔹 Allowed verification statuses (we want only these)
        # -----------------------------
        allowed_verification_set = {"verified", "admin_verified"}
        verification_statuses = list(allowed_verification_set)
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
            year = filters.year,
            candidate_name = filters.candidate_name,
            status = filters.status,
            verification_status = filters.verification_status,
            limit=filters.limit,
            offset=offset,
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
    year: Optional[int] = Query(None),
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
        candidate_record = controller.get_candidate_details_by_id(db, candidate_id,year)
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
        if role.lower() not in ["superadmin", "admin","employee"]:
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
        
        
## Make the Routes for MyNeta data fetching,Updateing,deleting and storing in the database

#Create a route to fetch the data:
from sqlalchemy.exc import IntegrityError

@router.post("/create_affidavit", status_code=status.HTTP_201_CREATED)
def create_affidavit(
    payload: schemas.AffidavitCreate,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    """
    Create a new affidavit entry. Unique constraint on (candidate_name, year, pc_name).
    Also populates candidate_history using controller.get_candidate_history.
    """
    # Verify token and get user
    try:
        email = get_email_from_token(token)
    except Exception as e:
        logger.error("Token decoding failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(employee_models.Employee).filter(employee_models.Employee.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role.lower() not in ["superadmin", "admin", "employee"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized role.")

    # Validate verification_status if provided in payload (role-based)
    if getattr(payload, "verification_status", None):
        new_vs = (payload.verification_status or "").strip()
        allowed_vs = {"under_review", "verified_employee", "verified_admin", "rejected_admin"}
        if new_vs not in allowed_vs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid verification_status. Allowed: {sorted(allowed_vs)}",
            )
        if role.lower() == "employee":
            allowed_for_employee = {"under_review", "verified_employee"}
            if new_vs not in allowed_for_employee:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Employees can only set verification_status to {sorted(allowed_for_employee)}",
                )

    # Prepare new affidavit (map status -> is_deleted if provided)
    is_deleted_flag = False
    if getattr(payload, "status", None) is not None:
        status_val = (payload.status or "").strip().lower()
        if status_val == "active":
            is_deleted_flag = False
        elif status_val == "inactive":
            is_deleted_flag = True
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid status. Allowed values: 'active' or 'inactive'.",
            )

    new = models.Affidavit(
        candidate_name=payload.candidate_name,
        party_name=payload.party_name,
        criminal_cases=payload.criminal_cases or 0,
        education=payload.education,
        age=payload.age,
        total_assets=payload.total_assets,
        liabilities=payload.liabilities,
        candidate_link=payload.candidate_link,
        year=payload.year,
        pc_name=payload.pc_name,
        state_name=payload.state_name,
        # soft-delete field
        is_deleted=is_deleted_flag,
        # verification_status (let DB default if not provided)
        verification_status=payload.verification_status if getattr(payload, "verification_status", None) else None,
    )

    try:
        db.add(new)
        db.commit()
        db.refresh(new)
    except IntegrityError as e:
        db.rollback()
        logger.error("DB IntegrityError on create_affidavit: %s", e)
        return {
            "success": False,
            "status": status.HTTP_400_BAD_REQUEST,
            "message": "Affidavit with same candidate_name, year and pc_name already exists.",
            "data": None,
        }
    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error creating affidavit: %s", e)
        raise HTTPException(status_code=500, detail="Internal Server Error")

    # Populate candidate_history (controller.get_candidate_history expects db + affidavit)
    try:
        history = controller.get_candidate_history(db, new)
        # Save candidate_history JSON back to the row
        new.candidate_history = history
        db.add(new)
        db.commit()
        db.refresh(new)
    except Exception as e:
        # Non-fatal: log and continue returning created object (but do not roll back creation)
        logger.exception("Failed to populate candidate_history for affidavit %s: %s", new.affidavit_id, e)

    return {
        "success": True,
        "status": status.HTTP_201_CREATED,
        "message": "Affidavit created successfully.",
        "data": schemas._to_dict(new),
    }

@router.get("/get_affidavit/{affidavit_id}")
def get_affidavit(
    affidavit_id: int,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    """
    Get affidavit by ID.
    - Employee → can only access affidavits from their assigned state/pc.
    - Superadmin/Admin → can access all affidavits.
    """
    try:
        email = get_email_from_token(token)
    except Exception as e:
        logger.error("Token decoding failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fetch user
    user = db.query(employee_models.Employee).filter(
        employee_models.Employee.email == email
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if role.lower() not in ["superadmin", "admin", "employee"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized role.")

    # Superadmin/Admin → can fetch directly
    if role.lower() in ["superadmin", "admin"]:
        obj = db.query(models.Affidavit).filter(
            models.Affidavit.affidavit_id == affidavit_id
        ).first()
    else:
        # Employee → restrict to assigned state/pc
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

        # Fetch affidavit
        obj = db.query(models.Affidavit).filter(
            models.Affidavit.affidavit_id == affidavit_id
        ).first()

        # Check assignment restriction
        if obj:
            state_match = assigned_state and assigned_state in (obj.state_name or "").strip().lower()
            pc_match = assigned_pc and assigned_pc in (obj.pc_name or "").strip().lower()

            if not (state_match or pc_match):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You cannot access affidavits outside your assigned state/constituency.",
                )

    if not obj:
        return {
            "success": False,
            "status": status.HTTP_404_NOT_FOUND,
            "message": "Affidavit not found.",
            "data": None,
        }

    # Convert affidavit to dict and add candidate history
    affidavit_data = _to_dict(obj)
    affidavit_data["candidate_history"] = controller.get_candidate_history(db, obj)

    return {
        "success": True,
        "status": status.HTTP_200_OK,
        "message": "Affidavit retrieved.",
        "data": affidavit_data,
    }

# @router.get("/get_affidavit/{affidavit_id}")
# def get_affidavit(
#     affidavit_id: int,
#     year: Optional[int] = None,               # <-- optional year selector
#     db: Session = Depends(get_db),
#     token: str = Depends(oauth2_scheme),
# ):
#     """
#     Get affidavit by ID.
#     - Employee → can only access affidavits from their assigned state/pc.
#     - Superadmin/Admin → can access all affidavits.

#     Behavior:
#     - Uses the affidavit_id to find the candidate_name (if present).
#     - Collects all affidavits with the same candidate_name, ordered by year DESC.
#     - By default returns the latest year affidavit for that candidate.
#     - If `year` query param is provided, returns that year's affidavit for the same candidate (if found).
#     """
#     try:
#         email = get_email_from_token(token)
#     except Exception as e:
#         logger.error("Token decoding failed: %s", e)
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid or expired token",
#             headers={"WWW-Authenticate": "Bearer"},
#         )

#     # Fetch user
#     user = db.query(employee_models.Employee).filter(
#         employee_models.Employee.email == email
#     ).first()
#     if not user:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

#     role = user.role.value if hasattr(user.role, "value") else str(user.role)

#     if role.lower() not in ["superadmin", "admin", "employee"]:
#         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized role.")

#     # 1) Fetch the requested affidavit to get candidate_name and to validate existence
#     base_q = db.query(models.Affidavit).filter(models.Affidavit.affidavit_id == affidavit_id)

#     # If employee, restrict access by assigned state/pc for initial fetch
#     if role.lower() == "employee":
#         profile = db.query(employee_models.EmployeeProfile).filter(
#             employee_models.EmployeeProfile.employee_id == user.id
#         ).first()
#         assigned_state = (profile.state_name or "").strip().lower() if profile and profile.state_name else None
#         assigned_pc = (profile.pc_name or "").strip().lower() if profile and profile.pc_name else None

#         if not assigned_state and not assigned_pc:
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="You are not assigned any state or constituency. Please contact support.",
#             )

#         # restrict initial fetch
#         if assigned_state:
#             base_q = base_q.filter(models.Affidavit.state_name.ilike(f"%{assigned_state}%"))
#         if assigned_pc:
#             base_q = base_q.filter(models.Affidavit.pc_name.ilike(f"%{assigned_pc}%"))

#     obj = base_q.first()

#     if not obj:
#         return {
#             "success": False,
#             "status": status.HTTP_404_NOT_FOUND,
#             "message": "Affidavit not found or not accessible.",
#             "data": None,
#         }

#     # If candidate_name exists, find all affidavits for same candidate (aliases)
#     candidate_name = (obj.candidate_name or "").strip()
#     aliases = []
#     selected_obj = obj  # default fallback

#     if candidate_name:
#         # build query to get all affidavits with same candidate name (case-insensitive)
#         aliases_q = db.query(models.Affidavit).filter(
#             func.lower(models.Affidavit.candidate_name) == candidate_name.lower()
#         )

#         # apply employee-level restrictions to alias list too
#         if role.lower() == "employee":
#             if assigned_state:
#                 aliases_q = aliases_q.filter(models.Affidavit.state_name.ilike(f"%{assigned_state}%"))
#             if assigned_pc:
#                 aliases_q = aliases_q.filter(models.Affidavit.pc_name.ilike(f"%{assigned_pc}%"))

#         # order by year desc so the first is the latest
#         aliases_q = aliases_q.order_by(models.Affidavit.year.desc())

#         alias_rows = aliases_q.all()

#         # build simple alias metadata for dropdowns
#         for a in alias_rows:
#             aliases.append(
#                 {
#                     "affidavit_id": a.affidavit_id,
#                     "year": a.year,
#                     "status": "inactive" if a.is_deleted else "active",
#                     "verification_status": a.verification_status,
#                 }
#             )

#         # If year param provided: try to pick that affidavit (for same candidate)
#         if year is not None:
#             match = next((a for a in alias_rows if a.year == year), None)
#             if not match:
#                 return {
#                     "success": False,
#                     "status": status.HTTP_404_NOT_FOUND,
#                     "message": f"No affidavit found for candidate '{candidate_name}' in year {year}.",
#                     "data": None,
#                 }
#             selected_obj = match
#         else:
#             # default: choose top (latest) year if present
#             if alias_rows:
#                 selected_obj = alias_rows[0]

#     # prepare response
#     affidavit_data = _to_dict(selected_obj)
#     affidavit_data["candidate_history"] = controller.get_candidate_history(db, selected_obj)

#     # annotate aliases with which one is selected
#     for alias in aliases:
#         alias["is_selected"] = alias["affidavit_id"] == selected_obj.affidavit_id

#     return {
#         "success": True,
#         "status": status.HTTP_200_OK,
#         "message": "Affidavit retrieved.",
#         "data": {
#             "affidavit": affidavit_data,
#             "aliases": aliases,   # useful for dropdown: id, year, status, verification_status, is_selected
#         },
#     }

@router.get("/list_affidavits")
def list_affidavits(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),

    # Filters
    candidate_name: Optional[str] = Query(None, description="Partial or full candidate name"),
    year: Optional[int] = Query(None),
    state_name: Optional[str] = Query(None),
    pc_name: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, description="active / inactive"),
    verification_status: Optional[str] = Query(None, description="under_review / verified_employee / verified_admin / rejected_admin"),
    party_name: Optional[str] = Query(None),
    age: Optional[float] = Query(None, description="Exact age. Use min/max code if you want range."),
    criminal_cases: Optional[int] = Query(None),
    liabilities: Optional[int] = Query(None),
):
    """
    List affidavits.
    - Employee → can only see affidavits for their assigned state_name & pc_name.
    - Superadmin/Admin → can see all affidavits.
    Pagination via skip & limit.
    """
    try:
        email = get_email_from_token(token)
    except Exception as e:
        logger.error("Token decoding failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fetch user
    user = db.query(employee_models.Employee).filter(
        employee_models.Employee.email == email
    ).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if role.lower() not in ["superadmin", "admin", "employee"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized role.")

    # Base query
    q = db.query(models.Affidavit)

    # Employee-level restrictions
    if role.lower() == "employee":
        profile = db.query(employee_models.EmployeeProfile).filter(
            employee_models.EmployeeProfile.employee_id == user.id
        ).first()

        assigned_state = (profile.state_name or "").strip().lower() if profile and profile.state_name else None
        assigned_pc = (profile.pc_name or "").strip().lower() if profile and profile.pc_name else None

        if not assigned_state and not assigned_pc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not assigned any state or constituency. Please contact support.",
            )

        if assigned_state:
            q = q.filter(models.Affidavit.state_name.ilike(f"%{assigned_state}%"))
        if assigned_pc:
            q = q.filter(models.Affidavit.pc_name.ilike(f"%{assigned_pc}%"))

    # Build filters from query params
    if candidate_name:
        q = q.filter(models.Affidavit.candidate_name.ilike(f"%{candidate_name.strip()}%"))
    if year is not None:
        q = q.filter(models.Affidavit.year == year)
    if state_name:
        q = q.filter(models.Affidavit.state_name.ilike(f"%{state_name.strip()}%"))
    if pc_name:
        q = q.filter(models.Affidavit.pc_name.ilike(f"%{pc_name.strip()}%"))
    if party_name:
        q = q.filter(models.Affidavit.party_name.ilike(f"%{party_name.strip()}%"))

    # Status mapping: expect "active" or "inactive"
    if status_filter is not None:
        sf = status_filter.strip().lower()
        if sf == "active":
            q = q.filter(models.Affidavit.is_deleted == False)
        elif sf == "inactive":
            q = q.filter(models.Affidavit.is_deleted == True)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status must be 'active' or 'inactive'")

    # Verification status exact match (enum/string)
    if verification_status:
        q = q.filter(models.Affidavit.verification_status == verification_status)

    # Numeric filters (exact matches). If you want ranges, you can add age_min/age_max etc.
    if age is not None:
        q = q.filter(models.Affidavit.age == age)
        # OR for range:
        # q = q.filter(models.Affidavit.age >= age_min, models.Affidavit.age <= age_max)

    if criminal_cases is not None:
        q = q.filter(models.Affidavit.criminal_cases == criminal_cases)

    if liabilities is not None:
        q = q.filter(models.Affidavit.liabilities == liabilities)

    # total + pagination
    total = q.count()
    items = q.offset(skip).limit(limit).all()

    items_with_history = []
    for i in items:
        d = _to_dict(i)
        d["candidate_history"] = controller.get_candidate_history(db, i)
        items_with_history.append(d)

    return {
        "success": True,
        "status": status.HTTP_200_OK,
        "message": f"Found {len(items)} affidavits (total matched: {total}).",
        "data": {
            "total": total,
            "count": len(items),
            "items": items_with_history,
        },
    }

@router.put("/update_affidavit/{affidavit_id}")
def update_affidavit(
    affidavit_id: int,
    payload: schemas.AffidavitUpdate,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    try:
        email = get_email_from_token(token)
    except Exception as e:        
        logger.error("Token decoding failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(employee_models.Employee).filter(employee_models.Employee.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role.lower() not in ["superadmin", "admin", "employee"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized role.")

    # Fetch affidavit
    obj = db.query(models.Affidavit).filter(models.Affidavit.affidavit_id == affidavit_id).first()
    if not obj:
        return {
            "success": False,
            "status": status.HTTP_404_NOT_FOUND,
            "message": "Affidavit not found.",
            "data": None,
        }

    # Employee → restrict updates to their assigned state/pc
    if role.lower() == "employee":
        profile = db.query(employee_models.EmployeeProfile).filter(
            employee_models.EmployeeProfile.employee_id == user.id
        ).first()
        assigned_state = (profile.state_name or "").strip().lower() if profile else None
        assigned_pc = (profile.pc_name or "").strip().lower() if profile else None

        state_match = assigned_state and assigned_state in (obj.state_name or "").strip().lower()
        pc_match = assigned_pc and assigned_pc in (obj.pc_name or "").strip().lower()

        if not (state_match or pc_match):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot update affidavits outside your assigned state/constituency.",
            )

    # Apply updates
    update_data = payload.dict(exclude_unset=True)
    
    # -----------------------
    # Handle status (map to is_deleted)
    # ------------------------
    if "status" in update_data:
        status_val = (update_data.pop("status") or "").strip().lower()
        if status_val == "active":
            obj.is_deleted = False
        elif status_val == "inactive":
            obj.is_deleted = True
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid status. Allowed values: 'active' or 'inactive'.",
            )

    # ------------------------
    # Handle verification_status with validation & role restrictions
    # ------------------------
    if "verification_status" in update_data:
        new_vs = (update_data.pop("verification_status") or "").strip()

        # Allowed statuses (keep these in sync with your DB enum)
        allowed_vs = {
            "under_review",
            "verified_employee",
            "verified_admin",
            "rejected_admin",
        }

        if new_vs not in allowed_vs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid verification_status. Allowed values: {sorted(allowed_vs)}",
            )

        # Role-based restrictions
        if role.lower() in {"superadmin", "admin"}:
            # admin can set any allowed status
            obj.verification_status = new_vs
        else:
            # employee: restrict what they can set
            allowed_for_employee = {"under_review", "verified_employee"}
            if new_vs not in allowed_for_employee:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Employees can only set verification_status to {sorted(allowed_for_employee)}",
                )
            obj.verification_status = new_vs
    
    # Handle candidate_history separately
    if "candidate_history" in update_data:
        obj.candidate_history = update_data.pop("candidate_history")
    
    # Apply remaining fields
    for field, value in update_data.items():
        setattr(obj, field, value)

    try:
        db.add(obj)
        db.commit()
        db.refresh(obj)
    except IntegrityError as e:
        db.rollback()
        logger.error("DB IntegrityError on update_affidavit: %s", e)
        return {
            "success": False,
            "status": status.HTTP_400_BAD_REQUEST,
            "message": "Update would violate database constraints (maybe duplicate candidate/year/pc).",
            "data": None,
        }
    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error updating affidavit: %s", e)
        raise HTTPException(status_code=500, detail="Internal Server Error")

    return {
        "success": True,
        "status": status.HTTP_200_OK,
        "message": "Affidavit updated successfully.",
        "data": _to_dict(obj),
    }


@router.delete("/delete_affidavit/{affidavit_id}")
def delete_affidavit(
    affidavit_id: int,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    try:
        email = get_email_from_token(token)
    except Exception as e:
        logger.error("Token decoding failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(employee_models.Employee).filter(employee_models.Employee.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role.lower() not in ["superadmin", "admin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized role.")

    # Fetch affidavit to soft-delete
    obj = db.query(models.Affidavit).filter(models.Affidavit.affidavit_id == affidavit_id).first()
    if not obj:
        return {
            "success": False,
            "status": status.HTTP_404_NOT_FOUND,
            "message": "Affidavit not found.",
            "data": None,
        }

    # If already soft-deleted, return a clear response
    if getattr(obj, "is_deleted", False):
        return {
            "success": False,
            "status": status.HTTP_400_BAD_REQUEST,
            "message": "Affidavit is already deleted (soft-deleted).",
            "data": {"affidavit_id": affidavit_id},
        }

    try:
        # Soft delete: mark deleted and set timestamp
        obj.is_deleted = True
        obj.deleted_at = datetime.now(timezone.utc)  # use UTC timestamp; change if you prefer local time
        db.add(obj)
        db.commit()
        db.refresh(obj)
    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error soft-deleting affidavit: %s", e)
        raise HTTPException(status_code=500, detail="Internal Server Error")

    return {
        "success": True,
        "status": status.HTTP_200_OK,
        "message": "Affidavit soft-deleted successfully.",
        "data": {
            "affidavit_id": affidavit_id,
            "is_deleted": obj.is_deleted,
            "deleted_at": obj.deleted_at,
        },
    }    
# -----------Updated by the candidate histories in the database--------   
#---------------------------------------------------------------------- 
@router.post("/update_candidate_histories")
def update_candidate_histories(db: Session = Depends(get_db)):
    try:
        affidavits = db.query(models.Affidavit).options(
            load_only(
                models.Affidavit.affidavit_id,
                models.Affidavit.candidate_name,
                models.Affidavit.age,
                models.Affidavit.year,
                models.Affidavit.pc_name,
            )
        ).all()

        updates = []
        for affidavit in affidavits:
            history = controller.get_candidate_history(db, affidavit)
            updates.append({
                "affidavit_id": affidavit.affidavit_id,
                "candidate_history": history
            })

        # bulk update instead of per-row commit
        db.bulk_update_mappings(models.Affidavit, updates)
        db.commit()

        return {"status": "success", "updated_records": len(updates)}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
def _normalize(s: Optional[str]) -> str:
    if not s:
        return ""
    s = str(s).strip().lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s

def _phonetic_keys(s: str):
    try:
        k = phonetics.dmetaphone(s)
        # ensure tuple of two strings
        if isinstance(k, tuple):
            return (k[0] or "", k[1] or "")
        return (k or "", "")
    except Exception:
        return ("", "")

def _contextual_boost(row, input_ctx: schemas.BulkNameSearchBody) -> float:
    boost = 0.0
    try:
        if input_ctx.year is not None and getattr(row, "year", None) == input_ctx.year:
            boost += 6.0
        if input_ctx.pc_name and getattr(row, "pc_name", None):
            if input_ctx.pc_name.strip().lower() == (getattr(row, "pc_name") or "").strip().lower():
                boost += 6.0
        if input_ctx.state_name and getattr(row, "state_name", None):
            if input_ctx.state_name.strip().lower() == (getattr(row, "state_name") or "").strip().lower():
                boost += 4.0
        if input_ctx.party_name and getattr(row, "party_name", None):
            if input_ctx.party_name.strip().lower() == (getattr(row, "party_name") or "").strip().lower():
                boost += 3.0
        # approximate age check (+/-2 years)
        if input_ctx.age is not None and getattr(row, "age", None) is not None:
            try:
                db_age = int(getattr(row, "age"))
                if abs(db_age - input_ctx.age) <= 2:
                    boost += 3.0
            except Exception:
                pass
    except Exception:
        pass
    return boost

@router.post("/simple_fuzzy_search_bulk")
def simple_fuzzy_search_bulk(
    body: schemas.BulkNameSearchBody,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    """
    POST body:
    {
      "names": ["abdul asif", "abdul asiph"],
      "threshold": 75,
      "pc_name": "kota",
      "year": 2019,
      "include_aliases": true
    }
    Response shape:
    {
      "success": bool,
      "status": int,
      "message": str,
      "data": {
         "<input_name>": { "matches": [ {candidate_name, score, rep_year, rep_pc, canonical_name?}, ... ] },
         ...
      }
    }
    """
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
    user = db.query(employee_models.Employee).filter(employee_models.Employee.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role.lower() not in ["superadmin", "admin", "employee"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized role.")

    if not body.names:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="names list required")

    threshold = max(0, min(100, int(body.threshold or 75)))
    sample_limit = int(body.sample_limit or 2000)

    # build base query constrained by optional context to reduce search space
    q = db.query(models.Affidavit)
    if body.pc_name:
        q = q.filter(models.Affidavit.pc_name.ilike(f"%{body.pc_name}%"))
    if body.state_name:
        q = q.filter(models.Affidavit.state_name.ilike(f"%{body.state_name}%"))
    if body.year:
        q = q.filter(models.Affidavit.year == body.year)
    if body.party_name:
        q = q.filter(models.Affidavit.party_name.ilike(f"%{body.party_name}%"))

    # fetch distinct candidate names (limited)
    rows = q.with_entities(
        models.Affidavit.candidate_name,
        models.Affidavit.year,
        models.Affidavit.pc_name,
        models.Affidavit.state_name,
        models.Affidavit.party_name,
        models.Affidavit.age,
    ).distinct().limit(sample_limit).all()

    # build alias map if table exists and user asked for it
    alias_map = {}
    if body.include_aliases and hasattr(models, "CandidateAlias"):
        try:
            alias_rows = db.query(models.CandidateAlias.alias_name, models.CandidateAlias.canonical_name).all()
            for a, c in alias_rows:
                if a and c:
                    alias_map[a] = c
        except Exception:
            alias_map = {}

    distinct_entries = [
        {
            "candidate_name": r.candidate_name,
            "year": getattr(r, "year", None),
            "pc_name": getattr(r, "pc_name", None),
            "state_name": getattr(r, "state_name", None),
            "party_name": getattr(r, "party_name", None),
            "age": getattr(r, "age", None),
        }
        for r in rows if r.candidate_name
    ]

    results: Dict[str, Any] = {}

    for input_name in body.names:
        input_norm = _normalize(input_name)
        input_ph = _phonetic_keys(input_norm)

        matches = []
        for entry in distinct_entries:
            cand = entry["candidate_name"]
            cand_norm = _normalize(cand)
            score = fuzz.token_sort_ratio(input_norm, cand_norm)  # 0..100

            # phonetic bump
            cand_ph = _phonetic_keys(cand_norm)
            if (input_ph[0] and input_ph[0] == cand_ph[0]) or (input_ph[1] and input_ph[1] == cand_ph[1]):
                score += 6.0

            # contextual boost from representative entry
            # We can use entry here because we pulled contextual columns along with name
            ctx_boost = _contextual_boost(type("R", (), entry), body)
            score += ctx_boost

            score = max(0.0, min(100.0, score))

            if score >= threshold:
                match = {
                    "candidate_name": cand,
                    "score": round(score, 2),
                    "rep_year": entry.get("year"),
                    "rep_pc": entry.get("pc_name"),
                    "rep_state": entry.get("state_name"),
                    "rep_party": entry.get("party_name"),
                }
                if body.include_aliases and cand in alias_map:
                    match["canonical_name"] = alias_map[cand]
                matches.append(match)

        matches = sorted(matches, key=lambda x: x["score"], reverse=True)
        results[input_name] = {"matches": matches}

    # prepare final response
    return {
        "success": True,
        "status": status.HTTP_200_OK,
        "message": f"Processed {len(body.names)} name(s); threshold={threshold}.",
        "data": results,
    }