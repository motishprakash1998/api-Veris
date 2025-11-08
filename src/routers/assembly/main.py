from loguru import logger
from sqlalchemy import or_
from src.database import get_db
from sqlalchemy.orm import Session
from typing import List, Optional, Set
from datetime import datetime, timezone
from src.routers.assembly import schemas
from sqlalchemy.exc import IntegrityError
from src.utils.jwt import get_email_from_token
from fastapi.security import OAuth2PasswordBearer
from src.routers.assembly.utilities import _to_dict
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from src.routers.employees import models as employee_models
from src.routers.assembly import my_neta_controller as controller
from fastapi import APIRouter, Depends, HTTPException,status,Query
from src.routers.assembly.models import assembly_myneta_models as models
from src.routers.assembly.controllers import (get_candidate_full_info_all_years,
                                              get_all_candidates_full_info,
                                              update_candidate_full_info,
                                              delete_candidate)

router = APIRouter(
    prefix="/api/assembly",
    tags=["Assembly"],
    responses={404: {"description": "Not found"}},
)

@router.get("/candidate/info")
def api_get_candidate_full_info_all_years(
    name: str, 
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)):
    """
    Get all information for a candidate by name (all years included),
    returned in a single 'data' dictionary with standardized response.
    """
    # ---------------------------
    # Token Verification
    # ---------------------------
    try:
        email = get_email_from_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        data = get_candidate_full_info_all_years(db, name)
        if not data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

        return {
            "success": True,
            "status": 200,
            "isActive": True,  # You can adjust this logic if you track candidate status later
            "message": f"Candidate information fetched successfully for '{name}'.",
            "data": data["data"],  # only extract the 'data' dict from controller response
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {str(e)}"
        )

@router.get("/candidates/all")
def api_get_all_candidates(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
    limit: int = Query(10, ge=1, le=100),
    page: int = Query(1, ge=1)
):
    """
    Get all candidates with their election information.
    Non-deleted only, sorted by election year descending.
    Supports pagination with limit and page query parameters.
    """
    
    # ---------------------------
    # Token Verification
    # ---------------------------
    try:
        email = get_email_from_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        data = get_all_candidates_full_info(db, limit=limit, page=page)
        if not data or len(data["data"]) == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No candidates found")

        return {
            "success": True,
            "status": 200,
            "message": f"Candidate information fetched successfully (page {page}).",
            "data": data["data"]
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {str(e)}"
        )


@router.put("/candidate/update/{candidate_id}")
def api_update_candidate(
    candidate_id: str,
    payload: schemas.GenericEditRequest,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    # Token verification
    try:
        email = get_email_from_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # prune None values from nested dicts
    def prune_none(d: dict) -> dict:
        out = {}
        for k, v in d.items():
            if v is None:
                continue
            if isinstance(v, dict):
                nested = prune_none(v)
                if nested:
                    out[k] = nested
            else:
                out[k] = v
        return out

    payload_dict = prune_none(payload.dict())

    if not payload_dict:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    updated = update_candidate_full_info(db, candidate_id, payload_dict, updated_by=email)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    if updated.get("no_changes"):
        return {
            "success": False,
            "status": 200,
            "user": email,
            "message": "No valid updatable fields provided; nothing changed.",
            "data": None
        }

    return {
        "success": True,
        "status": 200,
        "user": email,
        "message": "Candidate information updated successfully",
        "data": updated
    }

@router.delete("/candidate/delete/{candidate_id}")
def api_delete_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    """
    Soft delete a candidate by ID (set is_deleted=True).
    Requires valid token.
    """
    # ---------------------------
    # Verify token
    # ---------------------------
    try:
        email = get_email_from_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    deleted = delete_candidate(db, candidate_id, deleted_by=email)
    if not deleted:
        raise HTTPException(status_code=404, detail="Candidate not found or already deleted")

    return {
        "success": True,
        "status": 200,
        "user": email,
        "message": "Candidate soft deleted successfully",
        "data": deleted,
    }
    

@router.post("/candidate/create_affidavit", status_code=status.HTTP_201_CREATED)
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

    new = models.AssemblyAffidavit(
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

@router.get("/candidate/get_affidavit/{affidavit_id}")
def get_affidavit(
    affidavit_id: str,  # single id "123" or comma-separated "123,456"
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
    years: Optional[str] = Query(None, description="Optional comma-separated years filter, e.g., 2014,2019"),
):
    """
    Get affidavit(s) by ID(s), optional years filter, employee restrictions, and same-name/alias matches.
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role.lower() not in ["superadmin", "admin", "employee"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized role.")

    # -----------------------------
    # Parse affidavit IDs
    # -----------------------------
    try:
        requested_ids: List[int] = [int(x.strip()) for x in affidavit_id.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="affidavit_id must be integer or comma-separated integers."
        )

    # -----------------------------
    # Parse years filter
    # -----------------------------
    year_list: Optional[List[str]] = None
    if years:
        year_list = [y.strip() for y in years.split(",") if y.strip()]

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

    # -----------------------------
    # Base query for requested IDs
    # -----------------------------
    base_filters = [models.AssemblyAffidavit.affidavit_id.in_(requested_ids)]
    if role.lower() in ["superadmin", "admin"]:
        requested_objs = db.query(models.AssemblyAffidavit).filter(*base_filters).all()
    else:
        requested_objs = db.query(models.AssemblyAffidavit).filter(
            *base_filters,
            or_(
                models.AssemblyAffidavit.state_name.ilike(f"%{assigned_state}%"),
                models.AssemblyAffidavit.pc_name.ilike(f"%{assigned_pc}%")
            )
        ).all()

    if not requested_objs:
        return {
            "success": False,
            "status": status.HTTP_404_NOT_FOUND,
            "message": "No affidavits found for the given id(s) and filters.",
            "data": None,
        }

    # -----------------------------
    # Collect all affidavits (requested + same-name + aliases)
    # -----------------------------
    all_affidavit_objs: List[models.AssemblyAffidavit] = []
    seen_ids: Set[int] = set()

    for obj in requested_objs:
        if obj.affidavit_id in seen_ids:
            continue
        all_affidavit_objs.append(obj)
        seen_ids.add(obj.affidavit_id)

        candidate_name = (obj.candidate_name or "").strip()

        # Get aliases from candidate_history
        aliases: List[str] = []
        try:
            history = controller.get_candidate_history(db, obj)
            aliases = history.get("aliases", []) if isinstance(history, dict) else []
        except Exception:
            pass

        # Query for same-name or alias matches
        name_conditions = [models.AssemblyAffidavit.candidate_name.ilike(candidate_name)]
        for alias in aliases:
            name_conditions.append(models.AssemblyAffidavit.candidate_name.ilike(alias))

        same_name_query = db.query(models.AssemblyAffidavit).filter(
            or_(*name_conditions),
            models.AssemblyAffidavit.affidavit_id.notin_(list(seen_ids))
        )

        # Employee restrictions
        if role.lower() == "employee":
            same_name_query = same_name_query.filter(
                or_(
                    models.AssemblyAffidavit.state_name.ilike(f"%{assigned_state}%"),
                    models.AssemblyAffidavit.pc_name.ilike(f"%{assigned_pc}%")
                )
            )

        # Fetch all
        same_name_objs = same_name_query.all()
        for s in same_name_objs:
            if s.affidavit_id not in seen_ids:
                all_affidavit_objs.append(s)
                seen_ids.add(s.affidavit_id)

    # -----------------------------
    # Apply year filter (Python side, works even if DB column is string)
    # -----------------------------
    if year_list:
        filtered_objs = []
        for a in all_affidavit_objs:
            affidavit_year = str(a.year).strip() if a.year else ""
            # history_years = [str(y).strip() for y in (controller.get_candidate_history(db, a).get("years", []) if hasattr(controller, "get_candidate_history") else [])]

            if affidavit_year in year_list: #or any(y in year_list for y in history_years):
                filtered_objs.append(a)
        all_affidavit_objs = filtered_objs

    if not all_affidavit_objs:
        return {
            "success": False,
            "status": status.HTTP_404_NOT_FOUND,
            "message": "No affidavits found after applying year filter.",
            "data": None,
        }

    # -----------------------------
    # Convert to dicts + attach candidate_history
    # -----------------------------
    result_list = []
    for a in all_affidavit_objs:
        a_data = _to_dict(a)
        try:
            a_data["candidate_history"] = controller.get_candidate_history(db, a)
        except Exception:
            a_data["candidate_history"] = []
        result_list.append(a_data)

    return {
        "success": True,
        "status": 200,
        "message": "Affidavit(s) retrieved.",
        "data": result_list,
    }


@router.get("/candidate/list_affidavits")
def list_affidavits(
    page: int = Query(1, ge=1, description="Page number (starts at 1)"),
    limit: int = Query(10, ge=1, le=100, description="Items per page (max 100)"),
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),

    # Filters
    candidate_name: Optional[str] = Query(None, description="Partial or full candidate name"),
    year: Optional[int] = Query(None),
    state_name: Optional[str] = Query(None),
    pc_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="active / inactive"),
    verification_status: Optional[str] = Query(None, description="under_review / verified_employee / verified_admin / rejected_admin"),
    party_name: Optional[str] = Query(None),
    age: Optional[float] = Query(None, description="Exact age. Use min/max code if you want range."),
    criminal_cases: Optional[int] = Query(None),
    liabilities: Optional[int] = Query(None),
):
    """
    List affidavits (page-based pagination).
    - Employee → can only see affidavits for their assigned state_name & pc_name.
    - Superadmin/Admin → can see all affidavits.
    Pagination via page & limit.
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
    q = db.query(models.AssemblyAffidavit)

    # Employee-level restrictions
    profile = None
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
            q = q.filter(models.AssemblyAffidavit.state_name.ilike(f"%{assigned_state}%"))
        if assigned_pc:
            q = q.filter(models.AssemblyAffidavit.pc_name.ilike(f"%{assigned_pc}%"))

    # Build filters from query params
    if candidate_name:
        q = q.filter(models.AssemblyAffidavit.candidate_name.ilike(f"%{candidate_name.strip()}%"))
    if year is not None:
        q = q.filter(models.AssemblyAffidavit.year == year)
    if state_name:
        q = q.filter(models.AssemblyAffidavit.state_name.ilike(f"%{state_name.strip()}%"))
    if pc_name:
        q = q.filter(models.AssemblyAffidavit.pc_name.ilike(f"%{pc_name.strip()}%"))
    if party_name:
        q = q.filter(models.AssemblyAffidavit.party_name.ilike(f"%{party_name.strip()}%"))

    # Status mapping: expect "active" or "inactive"
    if status is not None:
        sf = status.strip().lower()
        if sf == "active":
            q = q.filter(models.AssemblyAffidavit.is_deleted.is_(False))
        elif sf == "inactive":
            q = q.filter(models.AssemblyAffidavit.is_deleted.is_(True))
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status must be 'active' or 'inactive'")

    # Verification status exact match (enum/string)
    if verification_status:
        q = q.filter(models.AssemblyAffidavit.verification_status == verification_status)

    # Numeric filters (exact matches). If you want ranges, you can add age_min/age_max etc.
    if age is not None:
        q = q.filter(models.AssemblyAffidavit.age == age)

    if criminal_cases is not None:
        q = q.filter(models.AssemblyAffidavit.criminal_cases == criminal_cases)

    if liabilities is not None:
        q = q.filter(models.AssemblyAffidavit.liabilities == liabilities)

    # total + pagination (page -> offset)
    total = q.count()
    offset = (page - 1) * limit
    items = q.offset(offset).limit(limit).all()

    items_with_history = []
    for i in items:
        d = _to_dict(i)
        d["candidate_history"] = controller.get_candidate_history(db, i)
        items_with_history.append(d)

    return {
        "success": True,
        "status": 200,
        "message": f"Found {len(items)} affidavits on page {page} (total matched: {total}).",
        "data": {
            "total": total,
            "count": len(items),
            "page": page,
            "limit": limit,
            "items": items_with_history,
        },
    }

@router.put("/candidate/update_affidavit/{affidavit_id}")
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
    obj = db.query(models.AssemblyAffidavit).filter(models.AssemblyAffidavit.affidavit_id == affidavit_id).first()
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
    if role.lower() not in ["superadmin", "admin","employee"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized role.")

    # Fetch affidavit to soft-delete
    obj = db.query(models.AssemblyAffidavit).filter(models.AssemblyAffidavit.affidavit_id == affidavit_id).first()
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