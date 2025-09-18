from typing import Optional, Dict, Any,List
from pydantic import BaseModel, Field
from decimal import Decimal
from src.routers.election_services.models.my_neta import Affidavit as AffidavitModel

# ----------------------
# Pydantic schemas
# ----------------------

class CandidateHistory(BaseModel):
    times_stood: int
    years: List[int]
    aliases: List[str]
    
    
class AffidavitCreate(BaseModel):
    candidate_name: str = Field(..., max_length=255)
    party_name: Optional[str] = Field(None, max_length=255)
    criminal_cases: Optional[int] = 0
    education: Optional[str] = Field(None, max_length=255)
    age: Optional[Decimal] = None
    total_assets: Optional[int] = None
    liabilities: Optional[int] = None
    candidate_link: Optional[str] = None
    year: int
    pc_name: Optional[str] = Field(None, max_length=255)
    state_name: Optional[str] = Field(None, max_length=255)
    candidate_history: Optional[CandidateHistory] = None


class AffidavitUpdate(BaseModel):
    candidate_name: Optional[str] = Field(None, max_length=255)
    party_name: Optional[str] = Field(None, max_length=255)
    criminal_cases: Optional[int] = None
    education: Optional[str] = Field(None, max_length=255)
    age: Optional[Decimal] = None
    total_assets: Optional[int] = None
    liabilities: Optional[int] = None
    candidate_link: Optional[str] = None
    year: Optional[int] = None
    pc_name: Optional[str] = Field(None, max_length=255)
    state_name: Optional[str] = Field(None, max_length=255)
    candidate_history: Optional[CandidateHistory] = None  
    


class AffidavitOut(BaseModel):
    affidavit_id: int
    candidate_name: str
    party_name: Optional[str]
    criminal_cases: int
    education: Optional[str]
    age: Optional[Decimal]
    total_assets: Optional[int]
    liabilities: Optional[int]
    candidate_link: Optional[str]
    year: int
    pc_name: Optional[str]
    state_name: Optional[str]
    candidate_history: Optional[CandidateHistory] = None  

    class Config:
        orm_mode = True


class BulkNameSearchBody(BaseModel):
    names: List[str]
    threshold: Optional[int] = 85
    sample_limit: Optional[int] = 2000
    pc_name: Optional[str] = None
    state_name: Optional[str] = None
    year: Optional[int] = None
    party_name: Optional[str] = None
    age: Optional[int] = None  # used for approximate age matching
    include_aliases: Optional[bool] = True
