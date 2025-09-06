from . import models
from . import schemas
from datetime import datetime
from src.database.db import get_db
from sqlalchemy.orm import Session
from loguru import logger as logging
from src.utils.jwt import  get_email_from_token
from fastapi.security import OAuth2PasswordBearer
from fastapi import APIRouter, Depends, HTTPException
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from src.routers.employees.models import employee as users_model

# Defining the router
router = APIRouter(
    prefix="/api/feedback",
    tags=["feedback"],
    responses={404: {"description": "Not found"}},
)

# Endpoint to create feedback
@router.post("/", response_model=schemas.FeedbackResponse)
def create_feedback(
    feedback_data: schemas.FeedbackCreate,
    token: str = Depends(OAuth2PasswordBearer(tokenUrl="token")),
    db: Session = Depends(get_db),
):
    """
    Create a feedback entry for the logged-in user.
    """
    try:
        # Decode user information from the token
        email = get_email_from_token(token)
        user = db.query(users_model.User).filter(users_model.User.email == email).first()
        logging.error(f"users:{user}")
        
        if not user:
            return {
                "success": False,
                "status": "404",  # status should be a string
                "isActive": False,
                "message": "User not found.",
                "data": None
            }

        # Use the logged-in user's ID for feedback
        user_id = user.id
        
        # Get the current timestamp
        current_timestamp = datetime.utcnow()

        # Create feedback entry
        feedback = models.Feedback(
            user_id=user_id,
            feedback=feedback_data.feedback,
            rating=feedback_data.rating,
            status="true",  # Ensure status is a string
            created_at=current_timestamp,
            updated_at=current_timestamp,
        )
        db.add(feedback)
        db.commit()
        db.refresh(feedback)

        return {
            "success": True,
            "status": "200",  # status should be a string
            "isActive": True,
            "message": "Feedback created successfully.",
            "data": {
                "id": feedback.id,
                "user_id": feedback.user_id,
                "feedback": feedback.feedback,
                "rating": feedback.rating,
                "status": feedback.status,
                "created_at": feedback.created_at.isoformat(),
                "updated_at": feedback.updated_at.isoformat(),
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return {
            "success": False,
            "status": "500",  # status should be a string
            "isActive": False,
            "message": "An unexpected error occurred.",
            "data": None
        }


