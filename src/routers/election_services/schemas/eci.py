# schemas/election_services.py
from pydantic import BaseModel,Field
from typing import List, Optional


class ElectionServiceItem(BaseModel):
    state_name: str | None
    pc_name: str | None
    candidate_name: str | None
    sex: str | None
    age: float | None
    category: str | None
    party_name: str | None
    party_symbol: str | None
    general_votes: int | None
    postal_votes: int | None
    total_votes: int | None
    over_total_electors_in_constituency: float | None
    over_total_votes_polled_in_constituency: float | None
    total_electors: int | None
    year: int | None

    # if you ever pass ORM objects instead of dicts, enable:
    model_config = {"from_attributes": True}


class ElectionServicesResponse(BaseModel):
    total: int
    items: List[ElectionServiceItem]
    
class ElectionFilters(BaseModel):
    pc_name: Optional[str] = None
    state_name: Optional[str] = None
    categories: Optional[List[str]] = None
    party_name: Optional[str] = None
    party_symbol: Optional[str] = None
    sex: Optional[str] = None
    min_age: Optional[float] = None
    max_age: Optional[float] = None
    limit: int = 10
    year: Optional[int] = None
    candidate_name: Optional[str] = None
    status: Optional[str] = None
    verification_status : Optional[str] = None
    page: Optional[int] = Field(1, ge=1)  # default page=1
    limit: Optional[int] = Field(10, ge=1, le=100)  # default 10 per page

class ElectionUpdateSchema(BaseModel):
    state_name: Optional[str] = None
    pc_name: Optional[str] = None
    candidate_name: Optional[str] = None
    sex: Optional[str] = None
    age: Optional[float] = None
    category: Optional[str] = None
    party_name: Optional[str] = None
    party_symbol: Optional[str] = None
    general_votes: Optional[int] = None
    postal_votes: Optional[int] = None
    total_votes: Optional[int] = None
    over_total_electors_in_constituency: Optional[float] = None
    over_total_votes_polled_in_constituency: Optional[float] = None
    total_electors: Optional[int] = None
    year: Optional[int] = None
    status: Optional[str] = None
    class Config:
        orm_mode = True