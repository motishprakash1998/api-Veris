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



@router.get("/dashboard")
def dashboard(
    filters: schemas.CommonFilters = Depends(),
    db: Session = Depends(get_db),
):
    """
    Dashboard-style API that returns all datasets together.
    Calls the wrapper function from crud.
    """
    employee_data = controllers.get_dashboard_data(db,filters)
    logging.error(f"Employee data :{employee_data}")
    dashboard_response_data = {"success": True,
                                "status": 200,
                                "message": "Dashboard data fetched.",
                                "data": employee_data
                }
    logging.error(f"dashboard_response_data:: {dashboard_response_data}")
    return dashboard_response_data