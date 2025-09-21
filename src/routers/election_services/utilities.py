from typing import Optional, Dict, Any
from src.routers.election_services.models.my_neta import Affidavit as AffidavitModel
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
        "pc_name": obj.pc_name,
        "state_name": obj.state_name,
        "status":"inactive" if obj.is_deleted else "active",
        "verification_status":obj.verification_status
        
    }

