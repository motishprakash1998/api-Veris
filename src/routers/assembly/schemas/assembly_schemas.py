# schemas.py
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from uuid import UUID

class ElectionBase(BaseModel):
    id: UUID
    year: int
    election_type: str
    state: Optional[str]

    class Config:
        orm_mode = True


class ConstituencyBase(BaseModel):
    id: UUID
    ac_no: int
    ac_name: str
    district: Optional[str]
    ac_type: Optional[str]
    state: Optional[str]

    class Config:
        orm_mode = True


class ConstituencyResultBase(BaseModel):
    id: UUID
    election_id: UUID
    constituency_id: UUID
    total_electors: Optional[int]
    total_votes: Optional[int]
    poll_percent: Optional[float]
    winning_candidate: Optional[str]
    winning_party: Optional[str]
    margin: Optional[int]

    class Config:
        orm_mode = True


class CandidateBase(BaseModel):
    id: UUID
    result_id: UUID
    position: Optional[int]
    candidate: Optional[str]
    party: Optional[str]
    votes: Optional[int]
    vote_percent: Optional[float]

    class Config:
        orm_mode = True


class MultipleStandingItem(BaseModel):
    candidate: str
    times_stood: int
    election_years: List[int]
    parties: List[str]
