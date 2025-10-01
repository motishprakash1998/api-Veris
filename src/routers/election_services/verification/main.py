import os
import uuid
import urllib.parse
# from . import models
# from . import schemas
from src.routers.election_services import  models
from src.routers.election_services import  schemas
# from . import controller
from src.routers.election_services.controller import (get_election_services,to_title,
                                                      get_candidate_details_by_id,
                                                      update_election_service_by_candidate,
                                                      _DictPayloadWrapper,
                                                      get_candidate_history)
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
from typing import List, Optional, Any, Dict,Tuple
from src.utils.jwt import get_email_from_token
from src.routers.employees import models as employee_models
from src.routers.employees import schemas as employee_schemas
from sqlalchemy.exc import IntegrityError
from src.routers.election_services.utilities import _to_dict
import re
from sqlalchemy.orm import load_only

load_dotenv ()

# Defining the router
router = APIRouter(
    prefix="/api/electionservices",
    tags=["Election Services"],
    responses={404: {"description": "Not found"}},
)

@router.get("/verification/list")
def fetch_election_data(
    filters: schemas.ElectionFilters = Depends(),  # ✅ schema for query params
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> Any:
    """
    Fetch election data with role-based restrictions and show only records
    where verification_status == "user_review".
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
        # 🔹 Call controller (force verification_status=user_review)
        # -----------------------------
        result = get_election_services(
            db=db,
            pc_name=allowed_pc,
            state_name=allowed_state,
            categories=filters.categories,
            party_name=filters.party_name,
            party_symbol=filters.party_symbol,
            sex=filters.sex,
            min_age=filters.min_age,
            max_age=filters.max_age,
            year=filters.year,
            candidate_name=filters.candidate_name,
            verification_status='rejected',
            limit=limit,
            offset=offset,
        )
        logger.error(f"Result is :{result}")
        
        # -----------------------------
        # 🔹 Format response
        # -----------------------------
        if isinstance(result, dict) and "details" in result:
            data = result["details"]["data"]
            logger.error(f"data is :{data}")
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
                        # keep verification_status explicit and normalized
                        "verification_status": to_title(item.get("verification_status") or "user_review"),
                        "data_type":to_title("eci")
                    })
                data["items"] = formatted_items
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
@router.get("/verification/get_candidate_info/{candidate_id}")
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
        candidate_record = get_candidate_details_by_id(db, candidate_id,year)
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

@router.put("/verification/update_by_candidate/{candidate_id}")
def update_candidate_data(
    candidate_id: int,
    payload: schemas.ElectionUpdateSchema,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> Any:
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

        updated = update_election_service_by_candidate(
            db=db,
            candidate_id=candidate_id,
            payload=wrapped_payload,
            election_id=None,      # or set if you want to target a specific election
            update_all=False,      # set True if you want to update all results
            role=role
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


