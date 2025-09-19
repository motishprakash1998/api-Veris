from fastapi import APIRouter, Depends , HTTPException, status
from typing import List 
from sqlalchemy.orm import Session ,Query
from . import schemas
from src.database import get_db
# from src.routers.employees import models, schemas
from loguru import logger as logging
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from src.utils.jwt import get_email_from_token
from . import  controllers

# Defining the router
router = APIRouter(
    prefix="/api/admin/dashboard",
    tags=["Admin Dashboard"],
    responses={404: {"description": "Not found"}},
)



@router.get("/dashboard", response_model=schemas.DashboardResponse)
def dashboard(
    filters: schemas.CommonFilters = Depends(),
    db: Session = Depends(get_db),
):
    """
    Dashboard-style API that returns all datasets together.
    Calls the wrapper function from crud.
    """
    return controllers.get_dashboard_data(db, filters)