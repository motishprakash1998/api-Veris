from sqlalchemy.orm import Session
from typing import Dict, Any, List
from src.routers.assembly.models import (
    ConstituencyCandidates,
    ConstituencyResults,
    ConstituencyMaster,
    ElectionMaster,
)
from sqlalchemy import asc,desc


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