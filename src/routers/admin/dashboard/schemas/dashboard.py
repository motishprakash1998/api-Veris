from typing import List, Optional
from pydantic import BaseModel

class CommonFilters(BaseModel):
    state_name: Optional[str] = None
    pc_name: Optional[str] = None
    year: Optional[int] = None
    party_name: Optional[str] = None
    candidate_name: Optional[str] = None


# Employee
class EmployeeOut(BaseModel):
    id: int
    email: str
    role: str
    status: str

    class Config:
        orm_mode = True


# MyNeta (Affidavit)
class AffidavitOut(BaseModel):
    affidavit_id: int
    candidate_name: str
    party_name: Optional[str]
    year: int
    pc_name: Optional[str]
    state_name: Optional[str]

    class Config:
        orm_mode = True


# ECI Result
class ResultOut(BaseModel):
    result_id: int
    candidate_name: str
    party_name: Optional[str]
    year: int
    state_name: str
    pc_name: str
    total_votes: Optional[int]

    class Config:
        orm_mode = True


# Final Dashboard Response
class DashboardResponse(BaseModel):
    eci_data: List[ResultOut]
    myneta_data: List[AffidavitOut]
    employee_data: List[EmployeeOut]
    waiting_employee_data: List[EmployeeOut]
