# utilities.py
from sqlalchemy.orm import Session
from typing import List
from models import ElectionMaster, ConstituencyMaster, ConstituencyResults, ConstituencyCandidates

def get_all_elections(db: Session) -> List[ElectionMaster]:
    return db.query(ElectionMaster).filter(ElectionMaster.is_deleted == False).all()

def get_all_constituencies(db: Session) -> List[ConstituencyMaster]:
    return db.query(ConstituencyMaster).filter(ConstituencyMaster.is_deleted == False).all()

def get_all_results(db: Session) -> List[ConstituencyResults]:
    return db.query(ConstituencyResults).filter(ConstituencyResults.is_deleted == False).all()

def get_all_candidates(db: Session) -> List[ConstituencyCandidates]:
    return db.query(ConstituencyCandidates).filter(ConstituencyCandidates.is_deleted == False).all()
