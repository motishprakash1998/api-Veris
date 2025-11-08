from fastapi import APIRouter, Depends, HTTPException,status,Query
from sqlalchemy.orm import Session
from src.routers.assembly.controllers import (get_candidate_full_info_all_years,
                                              get_all_candidates_full_info,
                                              update_candidate_full_info,
                                              delete_candidate)
from src.database import get_db
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from src.utils.jwt import get_email_from_token
from src.routers.assembly import schemas

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