# src/routers/election_services/controller.py
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from .models import eci as models
from fastapi import HTTPException, status
from .schemas import eci as schemas 
from sqlalchemy.orm import joinedload
from sqlalchemy import desc
from datetime import datetime
from loguru import logger


def get_election_services(
    db: Session,
    pc_name: Optional[str] = None,
    state_name: Optional[str] = None,
    categories: Optional[List[str]] = None,
    party_name: Optional[str] = None,
    party_symbol: Optional[str] = None,
    sex: Optional[str] = None,
    min_age: Optional[float] = None,
    max_age: Optional[float] = None,
    year: Optional[int] = None,
    limit: int = 10,
):
    """
    Fetch election services with flexible filtering.
    All text filters are applied case-insensitively.
    Supports filtering by `year` (Election.year).
    """
    try:
        # base query
        query = (
            db.query(
                models.State.state_name.label("state_name"),
                models.Constituency.pc_name.label("pc_name"),
                models.Candidate.candidate_id.label("candidate_id"),
                models.Candidate.candidate_name.label("candidate_name"),
                models.Candidate.gender.label("sex"),
                models.Candidate.age.label("age"),
                models.Candidate.category.label("category"),
                models.Party.party_name.label("party_name"),
                models.Party.party_symbol.label("party_symbol"),
                models.Result.general_votes.label("general_votes"),
                models.Result.postal_votes.label("postal_votes"),
                models.Result.total_votes.label("total_votes"),
                models.Result.over_total_electors_in_constituency.label("over_total_electors_in_constituency"),
                models.Result.over_total_votes_polled_in_constituency.label("over_total_votes_polled_in_constituency"),
                models.Constituency.total_electors.label("total_electors"),
                models.Election.year.label("year"),
            )
            .join(models.Constituency, models.Constituency.state_id == models.State.state_id)
            .join(models.Election, models.Election.pc_id == models.Constituency.pc_id)
            .join(models.Result, models.Result.election_id == models.Election.election_id)
            .join(models.Candidate, models.Candidate.candidate_id == models.Result.candidate_id)
            .join(models.Party, models.Party.party_id == models.Candidate.party_id)
        )
        # always exclude soft-deleted result rows
        query = query.filter(models.Result.is_deleted == False)

        filters = []

        # 1) pc_name filter
        if pc_name:
            filters.append(func.lower(models.Constituency.pc_name).like(f"%{pc_name.lower()}%"))

        # 2) state_name filter
        if state_name:
            filters.append(func.lower(models.State.state_name).like(f"%{state_name.lower()}%"))

        # 3) year filter (exact match)
        if year is not None:
            filters.append(models.Election.year == year)

        # 4) categories
        if categories:
            if isinstance(categories, list):
                categories = [c.lower() for c in categories]
                filters.append(func.lower(models.Candidate.category).in_(categories))
            else:
                filters.append(func.lower(models.Candidate.category).like(f"%{categories.lower()}%"))

        # 5) party filters
        if party_name:
            filters.append(func.lower(models.Party.party_name).like(f"%{party_name.lower()}%"))
        if party_symbol:
            filters.append(func.lower(models.Party.party_symbol).like(f"%{party_symbol.lower()}%"))

        # 6) sex
        if sex:
            filters.append(func.lower(models.Candidate.gender).like(f"%{sex.lower()}%"))

        # 7) age filters
        if (min_age is not None) and (max_age is not None):
            filters.append(and_(models.Candidate.age >= min_age, models.Candidate.age <= max_age))
        elif min_age is not None:
            filters.append(models.Candidate.age >= min_age)
        elif max_age is not None:
            filters.append(models.Candidate.age <= max_age)

        # apply filters
        if filters:
            query = query.filter(*filters)

        # ordering
        if pc_name:
            query = query.order_by(
                func.lower(models.Constituency.pc_name).asc(),
                func.lower(models.State.state_name).asc(),
                models.Election.year.desc()
            )
        else:
            # default alphabetical by state then pc, newest year first within same pc/state
            query = query.order_by(
                func.lower(models.State.state_name).asc(),
                func.lower(models.Constituency.pc_name).asc(),
                models.Election.year.desc()
            )

        # total count
        total = query.count()

        # fetch results safely for all SQLAlchemy versions
        try:
            rows = query.limit(limit).mappings().all()
            items = [dict(r) for r in rows]
        except AttributeError:
            rows = query.limit(limit).all()
            items = [dict(r._mapping) for r in rows]

        return {
            "details": {
                "status": "success",
                "status_code": 200,
                "message": f"Fetched {len(items)} record(s).",
                "data": {"total": total, "items": items},
            }
        }

    except Exception as exc:
        return {
            "details": {
                "status": "error",
                "status_code": 500,
                "message": "An unexpected error occurred while fetching election services.",
                "data": {"error": str(exc)},
            }
        }

def get_result_by_id(db: Session, result_id: int):
    """Fetch result record by ID"""
    return db.query(models.Result).filter(models.Result.result_id == result_id).first()
    
def get_candidate_details_by_id(
    db: Session,
    candidate_id: int
) -> Optional[List[dict]]:
    """
    Return detailed info for a candidate identified by candidate_id.
    Returns a list of dict (JSON serializable).
    """

    results = (
        db.query(models.Result)
        .options(
            joinedload(models.Result.candidate).joinedload(models.Candidate.party),
            joinedload(models.Result.election).joinedload(models.Election.constituency).joinedload(models.Constituency.state),
        )
        .filter(models.Result.candidate_id == candidate_id)
        .filter(models.Result.is_deleted == False) # exclude soft-deleted results
        .order_by(desc(models.Result.result_id))
        .all()
    )

    if not results:
        return None  # ya [] return karna hai toh aapke use case ke hisaab se

    items: List[dict] = []
    for result in results:
        candidate = result.candidate
        party = candidate.party if candidate else None
        election = result.election
        constituency = election.constituency if election else None
        state = constituency.state if constituency else None

        item = {
            "state_name": state.state_name if state else None,
            "pc_name": constituency.pc_name if constituency else None,
            "candidate_name": candidate.candidate_name if candidate else None,
            "sex": candidate.gender if candidate else None,
            "age": candidate.age if candidate else None,
            "category": candidate.category if candidate else None,
            "party_name": party.party_name if party else None,
            "party_symbol": party.party_symbol if party else None,
            "general_votes": result.general_votes if result else None,
            "postal_votes": result.postal_votes if result else None,
            "total_votes": result.total_votes if result else None,
            "over_total_electors_in_constituency": result.over_total_electors_in_constituency if result else None,
            "over_total_votes_polled_in_constituency": result.over_total_votes_polled_in_constituency if result else None,
            "total_electors": constituency.total_electors if constituency else None,
            "year": election.year if election else None,
        }
        items.append(item)

    return items

def update_election_service_by_candidate(
    db: Session,
    candidate_id: int,
    payload,
    election_id: Optional[int] = None,
    update_all: bool = False,
) -> Dict[str, Any] | List[Dict[str, Any]]:
    """
    Update election/candidate/result info based on candidate_id.
    - By default updates only the latest Result for the candidate.
    - If update_all=True, updates all Result rows for that candidate (optionally filtered by election_id).
    - If election_id provided, only Result(s) for that election are considered.
    Returns updated object (dict) or list of dicts (if update_all=True).
    """

    # Build base query for Result rows belonging to candidate (optionally filter by election)
    q = (
        db.query(models.Result)
        .options(
            joinedload(models.Result.candidate).joinedload(models.Candidate.party),
            joinedload(models.Result.election).joinedload(models.Election.constituency).joinedload(models.Constituency.state),
        )
        .filter(models.Result.candidate_id == candidate_id)
    )

    if election_id is not None:
        q = q.filter(models.Result.election_id == election_id)

    if update_all:
        results = q.all()
        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No result records found for the given candidate (and election, if provided).",
            )
    else:
        results = [q.order_by(desc(models.Result.result_id)).first()]  # latest only
        if not results[0]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Result record not found for the given candidate (and election, if provided).",
            )

    data = payload.dict(exclude_unset=True)

    updated_items: List[Dict[str, Any]] = []

    for result in results:
        # Load related objects (they should be present due to joinedload)
        election = result.election
        candidate = result.candidate
        constituency = election.constituency if election else None
        state = constituency.state if constituency else None
        party = candidate.party if candidate else None

        # -----------------------------
        # Election fields
        # -----------------------------
        if "year" in data and election:
            election.year = data["year"]

        if "pc_name" in data and constituency:
            constituency.pc_name = data["pc_name"]

        if "state_name" in data and state:
            state.state_name = data["state_name"]

        if "total_electors" in data and constituency:
            constituency.total_electors = data["total_electors"]

        # -----------------------------
        # Candidate fields
        # -----------------------------
        if "candidate_name" in data and candidate:
            candidate.candidate_name = data["candidate_name"]

        if "sex" in data and candidate:
            candidate.gender = data["sex"]

        if "age" in data and candidate:
            candidate.age = data["age"]

        if "category" in data and candidate:
            candidate.category = data["category"]

        if "party_name" in data:
            if party:
                party.party_name = data["party_name"]
            else:
                # If party doesn't exist, you may want to create it — here we just raise
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Party not found for candidate; cannot update party_name.",
                )

        if "party_symbol" in data:
            if party:
                party.party_symbol = data["party_symbol"]
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Party not found for candidate; cannot update party_symbol.",
                )

        # -----------------------------
        # Result fields
        # -----------------------------
        if "general_votes" in data:
            result.general_votes = data["general_votes"]

        if "postal_votes" in data:
            result.postal_votes = data["postal_votes"]

        if "total_votes" in data:
            result.total_votes = data["total_votes"]

        if "over_total_electors_in_constituency" in data:
            result.over_total_electors_in_constituency = data["over_total_electors_in_constituency"]

        if "over_total_votes_polled_in_constituency" in data:
            result.over_total_votes_polled_in_constituency = data["over_total_votes_polled_in_constituency"]

        # persist changes for this result (committing outside loop is fine too)
        db.add(result)
        if election:
            db.add(election)
        if constituency:
            db.add(constituency)
        if state:
            db.add(state)
        if candidate:
            db.add(candidate)
        if party:
            db.add(party)

        # We'll commit once after the loop to be more efficient
    db.commit()

    # refresh and prepare return payload(s)
    for result in results:
        db.refresh(result)
        election = result.election
        candidate = result.candidate
        constituency = election.constituency if election else None
        state = constituency.state if constituency else None
        party = candidate.party if candidate else None

        updated_items.append({
            "result_id": result.result_id,
            "state_name": state.state_name if state else None,
            "pc_name": constituency.pc_name if constituency else None,
            "candidate_name": candidate.candidate_name if candidate else None,
            "sex": candidate.gender if candidate else None,
            "age": candidate.age if candidate else None,
            "category": candidate.category if candidate else None,
            "party_name": party.party_name if party else None,
            "party_symbol": party.party_symbol if party else None,
            "general_votes": result.general_votes,
            "postal_votes": result.postal_votes,
            "total_votes": result.total_votes,
            "over_total_electors_in_constituency": result.over_total_electors_in_constituency,
            "over_total_votes_polled_in_constituency": result.over_total_votes_polled_in_constituency,
            "total_electors": constituency.total_electors if constituency else None,
            "year": election.year if election else None,
        })

    # return single dict for single update, or list for update_all
    return updated_items if update_all else updated_items[0]

def delete_candidate_results(
    db: Session,
    candidate_id: int,
    result_id: Optional[int] = None,
    delete_all: bool = False,
) -> List[Dict[str, Any]]:
    """
    Soft-delete (mark) Result row(s) for a candidate.
    - If result_id provided -> mark that specific Result (if it belongs to candidate).
    - Else if delete_all True -> mark all Results for candidate.
    - Else -> mark only the latest Result (highest result_id).
    Returns list of marked items.
    Raises 404 if no target rows found.
    """

    # base query (exclude already deleted ones)
    q = (
        db.query(models.Result)
        .options(
            joinedload(models.Result.candidate).joinedload(models.Candidate.party),
            joinedload(models.Result.election).joinedload(models.Election.constituency).joinedload(models.Constituency.state),
        )
        .filter(models.Result.candidate_id == candidate_id)
        .filter(models.Result.is_deleted == False)
    )

    if result_id is not None:
        q = q.filter(models.Result.result_id == result_id)

    if delete_all:
        results = q.all()
    else:
        if result_id is not None:
            res = q.first()
            results = [res] if res else []
        else:
            res = q.order_by(desc(models.Result.result_id)).first()
            results = [res] if res else []

    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No result records found to delete for the given candidate (and result_id if provided).",
        )

    marked_items: List[Dict[str, Any]] = []
    now = datetime.utcnow()

    for result in results:
        election = result.election
        candidate = result.candidate
        constituency = election.constituency if election else None
        state = constituency.state if constituency else None
        party = candidate.party if candidate else None

        # mark soft-delete
        result.is_deleted = True
        result.deleted_at = now

        marked_items.append({
            "result_id": result.result_id,
            "candidate_id": candidate.candidate_id if candidate else None,
            "state_name": state.state_name if state else None,
            "pc_name": constituency.pc_name if constituency else None,
            "candidate_name": candidate.candidate_name if candidate else None,
            "party_name": party.party_name if party else None,
            "total_votes": result.total_votes,
            "general_votes": result.general_votes,
            "postal_votes": result.postal_votes,
            "year": election.year if election else None,
            "deleted_at": now.isoformat() + "Z",
        })

        db.add(result)

    try:
        db.commit()
    except Exception as exc:
        logger.exception("DB commit failed while soft-deleting candidate results: %s", exc)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to commit soft-deletion.",
        )

    return marked_items

def _normalize_str_map(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {}
    for k, v in data.items():
        if isinstance(v, str):
            normalized[k] = v.strip().lower()
        else:
            normalized[k] = v
    return normalized

def create_candidate_entry(db: Session, payload) -> Dict[str, Any]:
    """
    Create (or reuse) State -> Constituency -> Party -> Candidate -> Election -> Result.
    payload is expected to support .dict(exclude_unset=True).
    Returns the created result dict.
    """
    data = payload.dict(exclude_unset=True)
    data = _normalize_str_map(data)

    # required minimal fields check (you can relax/add more)
    if "candidate_name" not in data or "pc_name" not in data or "state_name" not in data or "year" not in data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields: candidate_name, pc_name, state_name, year are required."
        )

    try:
        # 1) get or create State
        state = (
            db.query(models.State)
            .filter(func.lower(models.State.state_name) == data["state_name"])
            .first()
        )
        if not state:
            state = models.State(state_name=data["state_name"])
            db.add(state)
            db.flush()  # get state.state_id

        # 2) get or create Constituency (pc)
        constituency = (
            db.query(models.Constituency)
            .filter(func.lower(models.Constituency.pc_name) == data["pc_name"])
            .filter(models.Constituency.state_id == state.state_id)
            .first()
        )
        if not constituency:
            constituency = models.Constituency(
                pc_name=data["pc_name"],
                state_id=state.state_id,
                total_electors=data.get("total_electors"),
            )
            db.add(constituency)
            db.flush()

        # 3) get or create Party (if provided)
        party = None
        if "party_name" in data:
            party = (
                db.query(models.Party)
                .filter(func.lower(models.Party.party_name) == data["party_name"])
                .first()
            )
            if not party:
                party = models.Party(
                    party_name=data["party_name"],
                    party_symbol=data.get("party_symbol"),
                )
                db.add(party)
                db.flush()

        # 4) get or create Candidate
        # Prefer match by name+party if party available
        candidate_q = db.query(models.Candidate).filter(
            func.lower(models.Candidate.candidate_name) == data["candidate_name"]
        )
        if party:
            candidate_q = candidate_q.filter(models.Candidate.party_id == party.party_id)
        candidate = candidate_q.first()

        if not candidate:
            candidate = models.Candidate(
                candidate_name=data["candidate_name"],
                gender=data.get("sex"),
                age=data.get("age"),
                category=data.get("category"),
                party_id=party.party_id if party else None,
            )
            db.add(candidate)
            db.flush()

        # 5) get or create Election (by pc_id + year)
        election = (
            db.query(models.Election)
            .filter(models.Election.pc_id == constituency.pc_id)
            .filter(models.Election.year == data["year"])
            .first()
        )
        if not election:
            election = models.Election(
                year=data["year"],
                pc_id=constituency.pc_id,
                total_votes_polled_in_constituency=data.get("total_votes_polled_in_constituency"),
                valid_votes=data.get("valid_votes"),
            )
            db.add(election)
            db.flush()

        # 6) create Result (new row)
        result = models.Result(
            election_id=election.election_id,
            candidate_id=candidate.candidate_id,
            general_votes=data.get("general_votes"),
            postal_votes=data.get("postal_votes"),
            total_votes=data.get("total_votes"),
            over_total_electors_in_constituency=data.get("over_total_electors_in_constituency"),
            over_total_votes_polled_in_constituency=data.get("over_total_votes_polled_in_constituency"),
            over_total_valid_votes_polled_in_constituency=data.get("over_total_valid_votes_polled_in_constituency"),
            is_deleted=False,
            deleted_at=None,
        )
        db.add(result)
        db.flush()

        # 7) update any updatable container fields (like constituency.total_electors) if provided
        if "total_electors" in data:
            constituency.total_electors = data["total_electors"]
            db.add(constituency)

        # commit
        db.commit()
        db.refresh(result)
        # also refresh related objects if needed
        db.refresh(candidate)
        db.refresh(election)
        db.refresh(constituency)
        if party:
            db.refresh(party)
        if state:
            db.refresh(state)

        # prepare return payload (JSON serializable)
        return {
            "result_id": result.result_id,
            "state_name": state.state_name if state else None,
            "pc_name": constituency.pc_name if constituency else None,
            "candidate_id": candidate.candidate_id if candidate else None,
            "candidate_name": candidate.candidate_name if candidate else None,
            "sex": candidate.gender if candidate else None,
            "age": candidate.age if candidate else None,
            "category": candidate.category if candidate else None,
            "party_name": party.party_name if party else None,
            "party_symbol": party.party_symbol if party else None,
            "general_votes": result.general_votes,
            "postal_votes": result.postal_votes,
            "total_votes": result.total_votes,
            "over_total_electors_in_constituency": result.over_total_electors_in_constituency,
            "over_total_votes_polled_in_constituency": result.over_total_votes_polled_in_constituency,
            "total_electors": constituency.total_electors,
            "year": election.year,
        }

    except Exception as exc:
        logger.exception("Failed to create candidate entry: %s", exc)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create candidate entry: {str(exc)}"
        )