# utilities.py
from sqlalchemy.orm import Session
from typing import List

from typing import Optional, Dict, Any
from src.routers.assembly.models.assembly_myneta_models import AssemblyAffidavit as AffidavitModel
from src.routers.assembly.models.assembly_models import (ElectionMaster,
                                                         ConstituencyMaster, 
                                                         ConstituencyResults, 
                                                         ConstituencyCandidates)

def get_all_elections(db: Session) -> List[ElectionMaster]:
    return db.query(ElectionMaster).filter(ElectionMaster.is_deleted == False).all()

def get_all_constituencies(db: Session) -> List[ConstituencyMaster]:
    return db.query(ConstituencyMaster).filter(ConstituencyMaster.is_deleted == False).all()

def get_all_results(db: Session) -> List[ConstituencyResults]:
    return db.query(ConstituencyResults).filter(ConstituencyResults.is_deleted == False).all()

def get_all_candidates(db: Session) -> List[ConstituencyCandidates]:
    return db.query(ConstituencyCandidates).filter(ConstituencyCandidates.is_deleted == False).all()

# ----------------------
# Helpers
# ----------------------
def _to_dict(obj: AffidavitModel) -> Dict[str, Any]:
    return {
        "affidavit_id": obj.affidavit_id,
        "candidate_name": obj.candidate_name,
        "party_name": obj.party_name,
        "criminal_cases": obj.criminal_cases,
        "education": obj.education,
        "age": float(obj.age) if obj.age is not None else None,
        "total_assets": obj.total_assets,
        "liabilities": obj.liabilities,
        "candidate_link": obj.candidate_link,
        "year": obj.year,
        "ac_name": obj.ac_name,
        "state_name": obj.state_name,
        "status":"inactive" if obj.is_deleted else "active",
        "verification_status":obj.verification_status
        
    }

