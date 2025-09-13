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
from typing import List, Optional, Any

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

@router.get("/fetch_data")
def fetch_election_data(
    pc_name: Optional[str] = Query(None, description="Filter by parliamentary constituency name (pc_name)"),
    state_name: Optional[str] = Query(None, description="Filter by state name"),
    categories: Optional[List[str]] = Query(None, description="Filter by one or more candidate categories (repeatable)"),
    party_name: Optional[str] = Query(None, description="Filter by party name"),
    party_symbol: Optional[str] = Query(None, description="Filter by party symbol"),
    sex: Optional[str] = Query(None, description="Filter by candidate sex (male/female)"),
    min_age: Optional[float] = Query(None, description="Minimum candidate age"),
    max_age: Optional[float] = Query(None, description="Maximum candidate age"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of records to return (default 10)"),
    db: Session = Depends(get_db),
) -> Any:
    """
    Flexible fetch endpoint for Election Services.

    Behaviour:
    - If pc_name provided: prioritises pc_name filtering and orders by pc_name.
    - Otherwise orders alphabetically by state_name then pc_name.
    - All filters are optional.
    - Returns either:
      * legacy tuple-mapped response: {"total": int, "items": [...]}
      * or the new structured response: {"details": { status, status_code, message, data: {...} }}
    """
    try:
        # call controller with all supported filters
        result = controller.get_election_services(
            db=db,
            pc_name=pc_name,
            state_name=state_name,
            categories=categories,
            party_name=party_name,
            party_symbol=party_symbol,
            sex=sex,
            min_age=min_age,
            max_age=max_age,
            limit=limit,
        )

        # If controller returns a tuple (total, items) -> convert into your schema
        if isinstance(result, tuple) and len(result) == 2:
            total, items = result
            logger.info(f"Fetched {len(items)} records from the database (legacy tuple).")
            logger.debug(f"Results: {items}")
            # If you have a Pydantic response schema and want to return it:
            try:
                return schemas.ElectionServicesResponse(total=total, items=items)
            except Exception as conv_exc:
                # fallback to returning plain JSON if conversion fails
                logger.warning("Could not serialize to ElectionServicesResponse, returning plain dict", exc_info=conv_exc)
                return {"total": total, "items": items}

        # If controller returned the new professional dict with "details", return as-is
        if isinstance(result, dict) and "details" in result:
            logger.info("Fetched records from the database (structured response).")
            logger.debug(f"Structured result: {result}")
            return result

        # Unknown return shape — return it directly but log a warning
        logger.warning("Controller returned an unexpected shape; returning raw result.")
        logger.debug(f"Raw controller result: {result}")
        return result

    except HTTPException:
        # re-raise FastAPI HTTPException unchanged
        raise
    except Exception as exc:
        # professional error handling and message
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
