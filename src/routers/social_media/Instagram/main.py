from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
import requests

from . import controller

router = APIRouter(
    prefix="/api/instagram",
    tags=["Election Services"],
    responses={404: {"description": "Not found"}},)

@router.get("/")
def root():
    return {"msg": "Instagram scraper router. Use /validate?username=<username>"}


@router.get("/validate", summary="Validate Instagram username and return profile info")
def validate(username: str = Query(..., description="Instagram username to lookup")):
    """Lookup an Instagram user via RapidAPI and return a curated JSON response.

    Query parameters:
    - username: Instagram username to fetch
    """
    try:
        profile = controller.fetch_instagram_profile(username)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except requests.exceptions.RequestException as re:
        # network / upstream error
        raise HTTPException(status_code=502, detail=str(re))

    response = {
        "success": True,
        "status": 200,
        "message": f"Fetch the Data of {username} is successfully.",
        "data": profile,
    }
    return response
