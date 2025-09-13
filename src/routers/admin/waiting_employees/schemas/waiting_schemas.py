from pydantic import BaseModel
from typing import Optional
from src.routers.employees import models

class UpdatePermissionSchema(BaseModel):
    approve: bool  # True = approve → active, False = reject → inactive
    role: Optional[models.RoleEnum] = None
    state: Optional[str] = None
    country: Optional[str] = None
    pin_code: Optional[str] = None
    state_name: Optional[str] = None
    pc_name: Optional[str] = None
