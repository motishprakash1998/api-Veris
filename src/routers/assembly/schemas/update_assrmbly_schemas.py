from pydantic import BaseModel
from typing import Optional, Dict, Any

class CandidateUpdate(BaseModel):
    name: Optional[str]
    party: Optional[str]
    position: Optional[int]
    votes: Optional[int]
    vote_percent: Optional[float]

class ResultUpdate(BaseModel):
    total_electors: Optional[int]
    male_electors: Optional[int]
    female_electors: Optional[int]
    total_votes: Optional[int]
    poll_percent: Optional[float]
    nota_votes: Optional[int]
    nota_percent: Optional[float]
    winning_candidate: Optional[str]
    winning_party: Optional[str]
    margin: Optional[int]
    margin_percent: Optional[float]

class ConstituencyUpdate(BaseModel):
    ac_no: Optional[int]
    ac_name: Optional[str]
    district: Optional[str]
    ac_type: Optional[str]
    state: Optional[str]

class ElectionUpdate(BaseModel):
    year: Optional[int]
    election_type: Optional[str]
    state: Optional[str]

class CandidateEditRequest(BaseModel):
    candidate: Optional[CandidateUpdate]
    result: Optional[ResultUpdate]
    constituency: Optional[ConstituencyUpdate]
    election: Optional[ElectionUpdate]
    
    
# Accept generic payload (we'll validate allowed fields server-side)
class GenericEditRequest(BaseModel):
    candidate: Optional[Dict[str, Any]]
    result: Optional[Dict[str, Any]]
    constituency: Optional[Dict[str, Any]]
    election: Optional[Dict[str, Any]]