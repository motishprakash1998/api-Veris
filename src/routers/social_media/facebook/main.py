import requests
from . import controller
from src.database import get_db
from sqlalchemy.orm import Session
from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks

router = APIRouter(
    prefix="/api/facebook",
    tags=["Facebook Services"],
    responses={404: {"description": "Not found"}},
)

@router.get("/")
def root():
    return {"msg": "Facebook scraper router. Use /validate?username=<username>"}


@router.get("/validate", summary="Validate Facebook username and return profile info")
def validate(
    username: str = Query(..., description="Facebook username to lookup"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """Fetch Facebook profile and schedule background fetch for posts/metrics."""
    try:
        profile = controller.fetch_facebook_profile(username, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except requests.exceptions.RequestException as re:
        raise HTTPException(status_code=502, detail=str(re))

    # Kick off background job to fetch posts
    # background_tasks.add_task(controller.fetch_facebook_profile, username, db)

    response = {
        "success": True,
        "status": 200,
        "message": f"Fetched profile data for {username} successfully.",
        "data": profile,
    }
    return response
