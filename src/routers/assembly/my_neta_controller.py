# src/routers/election_services/controller.py
from sqlalchemy.orm import Session
from sqlalchemy import func
from loguru import logger
from rapidfuzz import fuzz ,process
from  src.routers.assembly import models as assembly_models



def get_candidate_history(db: Session, affidavit):
    target_name = affidavit.candidate_name.strip().lower()
    target_age = float(affidavit.age or 0)

    all_affidavits = (
        db.query(
            assembly_models.AssemblyAffidavit.candidate_name,
            assembly_models.AssemblyAffidavit.age,
            assembly_models.AssemblyAffidavit.year,
        )
        .filter(assembly_models.AssemblyAffidavit.ac_name.ilike(affidavit.ac_name.strip()))
        .filter(func.similarity(assembly_models.AssemblyAffidavit.candidate_name, affidavit.candidate_name) > 0.4)
        .all()
    )

    candidate_years = set()
    candidate_aliases = set()

    names = [a.candidate_name.strip().lower() for a in all_affidavits]
    matches = process.extract(
        target_name,
        names,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=80
    )
    matched_names = set(m[0] for m in matches)

    for aff in all_affidavits:
        cand_name = aff.candidate_name.strip().lower()
        if cand_name in matched_names:
            try:
                age_diff = abs(target_age - float(aff.age or 0))
            except Exception:
                age_diff = 0
            if age_diff <= 5:
                candidate_aliases.add(aff.candidate_name.strip())
                if aff.year:
                    candidate_years.add(int(aff.year))

    return {
        "times_stood": len(candidate_years),
        "years": sorted(candidate_years),
        "aliases": sorted(candidate_aliases),
    }

def to_title(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value.title()  # converts to Title Caps
    return value

