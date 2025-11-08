from sqlalchemy.orm import Session
from typing import Dict, Any, List
from src.routers.assembly.models import (
    ConstituencyCandidates,
    ConstituencyResults,
    ConstituencyMaster,
    ElectionMaster,
)
from sqlalchemy import asc,desc
from sqlalchemy.exc import SQLAlchemyError


def get_candidate_full_info_all_years(db: Session, candidate_name: str) -> Dict[str, Any]:
    """
    Fetch all election-related information for a candidate across all years
    where the candidate name appears (case-insensitive), returned as a single
    'data' dictionary.
    """
    # Query all candidates with the same name and not deleted
    candidates: List[ConstituencyCandidates] = (
        db.query(ConstituencyCandidates)
        .join(ConstituencyResults, ConstituencyCandidates.result_id == ConstituencyResults.id)
        .join(ElectionMaster, ConstituencyResults.election_id == ElectionMaster.id)
        .filter(ConstituencyCandidates.candidate.ilike(candidate_name))
        .filter(ConstituencyCandidates.is_deleted == False)
        .filter(ConstituencyResults.is_deleted == False)
        .filter(ElectionMaster.is_deleted == False)
        .order_by(asc(ElectionMaster.year))
        .all()
    )

    if not candidates:
        return None

    data_entries = []

    for candidate in candidates:
        result: ConstituencyResults = candidate.result
        constituency: ConstituencyMaster = result.constituency
        election: ElectionMaster = result.election

        entry = {
            "candidate": {
                "id": str(candidate.id),
                "name": candidate.candidate,
                "party": candidate.party,
                "position": candidate.position,
                "votes": candidate.votes,
                "vote_percent": float(candidate.vote_percent) if candidate.vote_percent else None,
            },
            "result": {
                "id": str(result.id),
                "total_electors": result.total_electors,
                "male_electors": result.male_electors,
                "female_electors": result.female_electors,
                "total_votes": result.total_votes,
                "poll_percent": float(result.poll_percent) if result.poll_percent else None,
                "nota_votes": result.nota_votes,
                "nota_percent": float(result.nota_percent) if result.nota_percent else None,
                "winning_candidate": result.winning_candidate,
                "winning_party": result.winning_party,
                "margin": result.margin,
                "margin_percent": float(result.margin_percent) if result.margin_percent else None,
            },
            "constituency": {
                "id": str(constituency.id),
                "ac_no": constituency.ac_no,
                "ac_name": constituency.ac_name,
                "district": constituency.district,
                "ac_type": constituency.ac_type,
                "state": constituency.state,
            },
            "election": {
                "id": str(election.id),
                "year": election.year,
                "election_type": election.election_type,
                "state": election.state,
            }
        }

        data_entries.append(entry)

    # Return all entries under a single 'data' dict
    return {"data": data_entries}


def get_all_candidates_full_info(db: Session, limit: int = 10, page: int = 1) -> Dict[str, Any]:
    """
    Fetch all candidates and their related election information.
    Only include non-deleted records.
    Sorted by election year descending.
    Supports pagination with limit and page.
    """
    offset_value = (page - 1) * limit

    candidates: List[ConstituencyCandidates] = (
        db.query(ConstituencyCandidates)
        .join(ConstituencyResults, ConstituencyCandidates.result_id == ConstituencyResults.id)
        .join(ElectionMaster, ConstituencyResults.election_id == ElectionMaster.id)
        .filter(ConstituencyCandidates.is_deleted == False)
        .filter(ConstituencyResults.is_deleted == False)
        .filter(ElectionMaster.is_deleted == False)
        .order_by(desc(ElectionMaster.year))
        .offset(offset_value)
        .limit(limit)
        .all()
    )

    data_entries = []

    for candidate in candidates:
        result: ConstituencyResults = candidate.result
        constituency: ConstituencyMaster = result.constituency
        election: ElectionMaster = result.election

        entry = {
            "candidate": {
                "id": str(candidate.id),
                "name": candidate.candidate,
                "party": candidate.party,
                "position": candidate.position,
                "votes": candidate.votes,
                "vote_percent": float(candidate.vote_percent) if candidate.vote_percent else None,
            },
            "result": {
                "id": str(result.id),
                "total_electors": result.total_electors,
                "male_electors": result.male_electors,
                "female_electors": result.female_electors,
                "total_votes": result.total_votes,
                "poll_percent": float(result.poll_percent) if result.poll_percent else None,
                "nota_votes": result.nota_votes,
                "nota_percent": float(result.nota_percent) if result.nota_percent else None,
                "winning_candidate": result.winning_candidate,
                "winning_party": result.winning_party,
                "margin": result.margin,
                "margin_percent": float(result.margin_percent) if result.margin_percent else None,
            },
            "constituency": {
                "id": str(constituency.id),
                "ac_no": constituency.ac_no,
                "ac_name": constituency.ac_name,
                "district": constituency.district,
                "ac_type": constituency.ac_type,
                "state": constituency.state,
            },
            "election": {
                "id": str(election.id),
                "year": election.year,
                "election_type": election.election_type,
                "state": election.state,
            }
        }

        data_entries.append(entry)

    return {"data": data_entries}


# Define allowed updatable fields per model (avoid updating id/is_deleted/etc)
ALLOWED_CANDIDATE_FIELDS = {"candidate", "party", "position", "votes", "vote_percent"}
ALLOWED_RESULT_FIELDS = {
    "total_electors", "male_electors", "female_electors", "total_votes",
    "poll_percent", "nota_votes", "nota_percent", "winning_candidate",
    "winning_party", "margin", "margin_percent"
}
ALLOWED_CONSTITUENCY_FIELDS = {"ac_no", "ac_name", "district", "ac_type", "state"}
ALLOWED_ELECTION_FIELDS = {"year", "election_type", "state"}


def update_candidate_full_info(
    db: Session, candidate_id: str, payload: Dict[str, Any], updated_by: str = None
) -> Dict[str, Any]:
    """
    Partially update candidate/result/constituency/election fields for a given candidate id.
    Only updates allowed fields. Payload example:
    {
      "candidate": {"party": "New Party"},
      "result": {"total_votes": 20000},
      "constituency": {"ac_name": "New Name"},
      "election": {"year": 2023}
    }
    """
    # Fetch candidate (ensure not deleted)
    candidate = (
        db.query(ConstituencyCandidates)
        .filter(ConstituencyCandidates.id == candidate_id)
        .filter(ConstituencyCandidates.is_deleted == False)
        .first()
    )
    if not candidate:
        return None

    result = candidate.result
    constituency = result.constituency
    election = result.election

    try:
        # Helper to update only allowed fields
        def apply_updates(obj, updates: Dict[str, Any], allowed_fields: set):
            changed = False
            for field, value in updates.items():
                if field in allowed_fields and value is not None and hasattr(obj, field):
                    setattr(obj, field, value)
                    changed = True
            return changed

        any_change = False

        cand_payload = payload.get("candidate") or {}
        if cand_payload:
            if apply_updates(candidate, cand_payload, ALLOWED_CANDIDATE_FIELDS):
                any_change = True

        res_payload = payload.get("result") or {}
        if res_payload:
            if apply_updates(result, res_payload, ALLOWED_RESULT_FIELDS):
                any_change = True

        const_payload = payload.get("constituency") or {}
        if const_payload:
            if apply_updates(constituency, const_payload, ALLOWED_CONSTITUENCY_FIELDS):
                any_change = True

        elec_payload = payload.get("election") or {}
        if elec_payload:
            if apply_updates(election, elec_payload, ALLOWED_ELECTION_FIELDS):
                any_change = True

        if not any_change:
            # nothing valid to update
            return {"no_changes": True}

        # commit
        db.add(candidate)
        db.add(result)
        db.add(constituency)
        db.add(election)
        db.commit()

        # refresh
        db.refresh(candidate)
        db.refresh(result)
        db.refresh(constituency)
        db.refresh(election)

        # build updated response
        response = {
            "candidate": {
                "id": str(candidate.id),
                "name": candidate.candidate,
                "party": candidate.party,
                "position": candidate.position,
                "votes": candidate.votes,
                "vote_percent": float(candidate.vote_percent) if candidate.vote_percent is not None else None,
            },
            "result": {
                "id": str(result.id),
                "total_electors": result.total_electors,
                "male_electors": result.male_electors,
                "female_electors": result.female_electors,
                "total_votes": result.total_votes,
                "poll_percent": float(result.poll_percent) if result.poll_percent is not None else None,
                "nota_votes": result.nota_votes,
                "nota_percent": float(result.nota_percent) if result.nota_percent is not None else None,
                "winning_candidate": result.winning_candidate,
                "winning_party": result.winning_party,
                "margin": result.margin,
                "margin_percent": float(result.margin_percent) if result.margin_percent is not None else None,
            },
            "constituency": {
                "id": str(constituency.id),
                "ac_no": constituency.ac_no,
                "ac_name": constituency.ac_name,
                "district": constituency.district,
                "ac_type": constituency.ac_type,
                "state": constituency.state,
            },
            "election": {
                "id": str(election.id),
                "year": election.year,
                "election_type": election.election_type,
                "state": election.state,
            }
        }

        return response

    except SQLAlchemyError:
        db.rollback()
        raise
    


def delete_candidate(db: Session, candidate_id: str, deleted_by: str = None) -> dict:
    """
    Soft delete a candidate by setting is_deleted = True.
    """
    candidate = (
        db.query(ConstituencyCandidates)
        .filter(ConstituencyCandidates.id == candidate_id)
        .filter(ConstituencyCandidates.is_deleted == False)
        .first()
    )

    if not candidate:
        return None

    try:
        candidate.is_deleted = True
        db.add(candidate)
        db.commit()
        db.refresh(candidate)

        return {
            "id": str(candidate.id),
            "name": candidate.candidate,
            "party": candidate.party,
            "is_deleted": candidate.is_deleted,
            "deleted_by": deleted_by,
        }

    except SQLAlchemyError as e:
        db.rollback()
        raise e