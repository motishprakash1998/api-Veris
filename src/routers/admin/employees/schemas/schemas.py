from pydantic import BaseModel
from typing import Optional
from datetime import datetime   
from src.routers.employees import models

class UpdateEmployeeSchema(BaseModel):
    status: Optional[models.StatusEnum] = None
    role: Optional[models.RoleEnum] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    pin_code: Optional[str] = None
    state_name: Optional[str] = None
    pc_name: Optional[str] = None
