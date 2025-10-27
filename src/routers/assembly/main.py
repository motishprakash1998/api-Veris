from fastapi import APIRouter, Depends, HTTPException,status,Query
from sqlalchemy.orm import Session
from src.routers.assembly.controllers import get_candidate_full_info_all_years,get_all_candidates_full_info
from src.database import get_db
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from src.utils.jwt import get_email_from_token

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