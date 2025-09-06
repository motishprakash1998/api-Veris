from pydantic import BaseModel
from typing import Optional
from datetime import datetime
# Pydantic models for request validation
class FeedbackCreate(BaseModel):
    rating: int
    feedback: str

class FeedbackUpdate(BaseModel):
    feedback: str = None
    rating: int = None
    status: str = None

    class Config:
        orm_mode = True

class FeedbackResponseData(BaseModel):
    id: int
    user_id: int
    feedback: str
    rating: int
    status: str  # Make sure status is a string (e.g., "true" or "false")
    created_at: datetime
    updated_at: datetime
    
    

class FeedbackResponse(BaseModel):
    success: bool
    status: str  # Ensure status is a string (e.g., "200", "404")
    isActive: bool
    message: str
    data: Optional[FeedbackResponseData]

    class Config:
        orm_mode = True
