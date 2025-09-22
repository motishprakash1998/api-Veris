# src/routers/election_services/controller.py
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, func ,case
from . import models
from fastapi import HTTPException, status
from .schemas import eci as schemas 
from sqlalchemy.orm import joinedload
from sqlalchemy import desc
from datetime import datetime
from loguru import logger
from rapidfuzz import fuzz ,process
from collections import defaultdict


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
    candidate_name:Optional[str]= None,
    status: Optional[str] = None,
    verification_status:Optional[str]=None,
    limit: int = 10,
    offset: int = 0,   # ✅ NEW
):
    """
    Fetch election services with flexible filtering and pagination.
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
                case(
                (models.Result.is_deleted == False, "active"),
                (models.Result.is_deleted == True, "inactive"),
                ).label("status"),
                models.Result.verification_status.label("verification_status"),
                )
            .join(models.Constituency, models.Constituency.state_id == models.State.state_id)
            .join(models.Election, models.Election.pc_id == models.Constituency.pc_id)
            .join(models.Result, models.Result.election_id == models.Election.election_id)
            .join(models.Candidate, models.Candidate.candidate_id == models.Result.candidate_id)
            .join(models.Party, models.Party.party_id == models.Candidate.party_id)
        )

        # query = query.filter(models.Result.is_deleted == False)

        filters = []

        # 🔹 Apply filters (same as before)...
        
        # 🔹 Status filter (soft-delete)
        if status is not None:
            if status.lower() == "active":
                filters.append(models.Result.is_deleted == False)
            elif status.lower() == "inactive":
                filters.append(models.Result.is_deleted == True)

        # 🔹 Verification status filter
        if verification_status is not None:
            filters.append(models.Result.verification_status == verification_status)
        if candidate_name is not None:
            filter.append(func.lower(models.Candidate.candidate_name).like(f"%{candidate_name.lower()}%"))
        if pc_name:
            filters.append(func.lower(models.Constituency.pc_name).like(f"%{pc_name.lower()}%"))
        if state_name:
            filters.append(func.lower(models.State.state_name).like(f"%{state_name.lower()}%"))
        if year is not None:
            filters.append(models.Election.year == year)
        if categories:
            if isinstance(categories, list):
                filters.append(func.lower(models.Candidate.category).in_([c.lower() for c in categories]))
            else:
                filters.append(func.lower(models.Candidate.category).like(f"%{categories.lower()}%"))
        if party_name:
            filters.append(func.lower(models.Party.party_name).like(f"%{party_name.lower()}%"))
        if party_symbol:
            filters.append(func.lower(models.Party.party_symbol).like(f"%{party_symbol.lower()}%"))
        if sex:
            filters.append(func.lower(models.Candidate.gender).like(f"%{sex.lower()}%"))
        if (min_age is not None) and (max_age is not None):
            filters.append(and_(models.Candidate.age >= min_age, models.Candidate.age <= max_age))
        elif min_age is not None:
            filters.append(models.Candidate.age >= min_age)
        elif max_age is not None:
            filters.append(models.Candidate.age <= max_age)
        
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
            query = query.order_by(
                func.lower(models.State.state_name).asc(),
                func.lower(models.Constituency.pc_name).asc(),
                models.Election.year.desc()
            )

        # total count BEFORE pagination
        total = query.count()

        # 🔹 Apply pagination
        try:
            rows = query.offset(offset).limit(limit).mappings().all()
            logger.error(f"Rows is :{rows}")
            items = [dict(r) for r in rows]
        except AttributeError:
            rows = query.offset(offset).limit(limit).all()
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

# def get_candidate_details_by_id(
#     db: Session,
#     candidate_id: int,
#     year: Optional[int] = None   # 🔹 extra param
# ) -> Optional[List[dict]]:
#     """
#     Get full election history of a candidate (same person, same constituency/PC)
#     across years, even if candidate_id changed.
#     If year is provided, filter by that year.
#     If not provided, pick the latest year automatically.
#     """
#     # Step 1: get candidate info
#     candidate = (
#         db.query(models.Candidate)
#         .join(models.Result, models.Result.candidate_id == models.Candidate.candidate_id)
#         .join(models.Election, models.Election.election_id == models.Result.election_id)
#         .join(models.Constituency, models.Constituency.pc_id == models.Election.pc_id)
#         .filter(models.Candidate.candidate_id == candidate_id)
#         .first()
#     )
#     if not candidate:
#         return None

#     candidate_name = candidate.candidate_name

#     # Step 2: find the PC of this candidate
#     election = (
#         db.query(models.Election)
#         .join(models.Result, models.Result.election_id == models.Election.election_id)
#         .filter(models.Result.candidate_id == candidate_id)
#         .first()
#     )
#     if not election:
#         return None

#     pc_id = election.pc_id  # ✅ restrict to same constituency

#     # Step 3: find all candidate_ids with same name IN same PC
#     candidate_ids = [
#         r.candidate_id
#         for r in (
#             db.query(models.Result.candidate_id)
#             .join(models.Election, models.Election.election_id == models.Result.election_id)
#             .join(models.Candidate, models.Candidate.candidate_id == models.Result.candidate_id)
#             .filter(func.lower(models.Candidate.candidate_name) == candidate_name.lower())
#             .filter(models.Election.pc_id == pc_id)  # ✅ same constituency
#             .all()
#         )
#     ]
#     if not candidate_ids:
#         return None
        
#     from collections import defaultdict

#     rows = (
#         db.query(models.Result.candidate_id, models.Election.year)
#         .join(models.Election, models.Election.election_id == models.Result.election_id)
#         .filter(models.Result.candidate_id.in_(candidate_ids))
#         .filter(models.Result.is_deleted == False)   # same filter as results
#         .distinct()  # distinct (candidate_id, year)
#         .order_by(models.Result.candidate_id, models.Election.year.desc())
#         .all()
#     )
#     # rows looks like [(123, 2024), (123, 2019), (456, 2024), ...]

#     years_by_candidate = defaultdict(list)
#     for cid, yr in rows:
#         years_by_candidate[cid].append(int(yr))

#     # # If you want plain dict:
#     # years_by_candidate = {cid: years_by_candidate[cid] for cid in years_by_candidate}


#     # Step 4: fetch results
#     query = (
#         db.query(models.Result)
#         .join(models.Election, models.Election.election_id == models.Result.election_id)  # ✅ Explicit join
#         .options(
#             joinedload(models.Result.candidate).joinedload(models.Candidate.party),
#             joinedload(models.Result.election).joinedload(models.Election.constituency).joinedload(models.Constituency.state),
#         )
#         .filter(models.Result.candidate_id.in_(candidate_ids))
#         # .filter(models.Result.is_deleted == False)
#     )

#     if year:
#         query = query.filter(models.Election.year == year)  # ✅ filter by year
#     else:
#         # Agar year nahi diya, to latest year pick karo
#         latest_year = (
#             db.query(func.max(models.Election.year))
#             .join(models.Result, models.Result.election_id == models.Election.election_id)
#             .filter(models.Result.candidate_id.in_(candidate_ids))
#             .scalar()
#         )
#         if latest_year:
#             query = query.filter(models.Election.year == latest_year)

#     results = query.order_by(models.Election.year.desc()).all()

#     # Step 5: format output
#     items: List[dict] = []
#     for result in results:
#         candidate = result.candidate
#         party = candidate.party if candidate else None
#         election = result.election
#         constituency = election.constituency if election else None
#         state = constituency.state if constituency else None

#         items.append({
#             "state_name": state.state_name if state else None,
#             "pc_name": constituency.pc_name if constituency else None,
#             "candidate_name": candidate.candidate_name if candidate else None,
#             "sex": candidate.gender if candidate else None,
#             "age": candidate.age if candidate else None,
#             "category": candidate.category if candidate else None,
#             "party_name": party.party_name if party else None,
#             "party_symbol": party.party_symbol if party else None,
#             "general_votes": result.general_votes,
#             "postal_votes": result.postal_votes,
#             "total_votes": result.total_votes,
#             "total_electors": constituency.total_electors if constituency else None,
#             "year": election.year if election else None,
#             "status":"inactive" if result.is_deleted else "active",
#             "verification_status": result.verification_status,
#             "election_year":years_by_candidate
#         })
        
#     logger.error(f"Election years is : {years_by_candidate}")

#     return items
# from typing import Optional, List, Dict
# from collections import defaultdict
# from sqlalchemy import func, and_

def get_candidate_details_by_id(
    db: Session,
    candidate_id: int,
    year: Optional[int] = None
) -> Optional[List[dict]]:
    """
    Robust version that ensures 'election_year' mapping is built correctly.
    Returns a flat list of result rows (one dict per Result) with:
      "election_year": { "<cid>": [years...], ... }
    """

    # 1) sample candidate & pc_id
    sample_candidate = (
        db.query(models.Candidate)
        .join(models.Result, models.Result.candidate_id == models.Candidate.candidate_id)
        .join(models.Election, models.Election.election_id == models.Result.election_id)
        .filter(models.Candidate.candidate_id == candidate_id)
        .first()
    )
    if not sample_candidate:
        logger.warning(f"No sample candidate found for id={candidate_id}")
        return None

    candidate_name = (sample_candidate.candidate_name or "").strip()
    if not candidate_name:
        logger.warning(f"Candidate name empty for id={candidate_id}")
        return None

    sample_election = (
        db.query(models.Election)
        .join(models.Result, models.Result.election_id == models.Election.election_id)
        .filter(models.Result.candidate_id == candidate_id)
        .first()
    )
    if not sample_election:
        logger.warning(f"No sample election found for candidate_id={candidate_id}")
        return None
    pc_id = sample_election.pc_id

    # 2) find all candidate_ids in the same PC with same normalized name
    # Normalize trimming and lower-casing. Also try to collapse multiple spaces.
    normalized_name = " ".join(candidate_name.split()).lower()

    candidate_id_rows = (
        db.query(models.Result.candidate_id)
        .join(models.Candidate, models.Candidate.candidate_id == models.Result.candidate_id)
        .join(models.Election, models.Election.election_id == models.Result.election_id)
        .filter(func.lower(func.trim(func.replace(models.Candidate.candidate_name, '  ', ' '))) == normalized_name)
        .filter(models.Election.pc_id == pc_id)
        .distinct()
        .all()
    )
    candidate_ids = [r.candidate_id for r in candidate_id_rows]
    if not candidate_ids:
        # fallback: loosen matching (contains)
        candidate_id_rows = (
            db.query(models.Result.candidate_id)
            .join(models.Candidate, models.Candidate.candidate_id == models.Result.candidate_id)
            .join(models.Election, models.Election.election_id == models.Result.election_id)
            .filter(func.lower(models.Candidate.candidate_name).like(f"%{normalized_name}%"))
            .filter(models.Election.pc_id == pc_id)
            .distinct()
            .all()
        )
        candidate_ids = [r.candidate_id for r in candidate_id_rows]

    if not candidate_ids:
        logger.error(f"No candidate_ids matched name='{candidate_name}' (normalized='{normalized_name}') in pc_id={pc_id}")
        return None

    logger.info(f"Found candidate_ids for name='{candidate_name}': {candidate_ids} in pc_id={pc_id}")

    # 3) Build years_by_candidate mapping.
    # Include both deleted and non-deleted rows so we capture historical years.
    rows = (
        db.query(models.Result.candidate_id, models.Election.year)
        .join(models.Election, models.Election.election_id == models.Result.election_id)
        .filter(models.Result.candidate_id.in_(candidate_ids))
        .distinct()
        .order_by(models.Result.candidate_id, models.Election.year.desc())
        .all()
    )

    years_by_candidate: Dict[int, List[int]] = defaultdict(list)
    for cid, yr in rows:
        # guard: skip null years
        try:
            if yr is None:
                continue
            # ensure int type
            years_by_candidate[cid].append(int(yr))
        except Exception:
            # try safe cast from string
            try:
                years_by_candidate[cid].append(int(str(yr).strip()))
            except Exception:
                logger.debug(f"Skipping invalid year value '{yr}' for cid={cid}")

    # ensure unique sorted descending lists
    for cid in list(years_by_candidate.keys()):
        uniq = sorted(list(dict.fromkeys(years_by_candidate[cid])), reverse=True)
        years_by_candidate[cid] = uniq

    # If mapping is empty, log and continue (we'll still return rows but mapping will be empty arrays)
    if not years_by_candidate:
        logger.warning(f"years_by_candidate mapping empty for candidate_ids={candidate_ids}")

    # 4) fetch full Result rows (with relations). We return one item per Result row (flat).
    query = (
        db.query(models.Result)
        .join(models.Election, models.Election.election_id == models.Result.election_id)
        .options(
            joinedload(models.Result.candidate).joinedload(models.Candidate.party),
            joinedload(models.Result.election).joinedload(models.Election.constituency).joinedload(models.Constituency.state),
        )
        .filter(models.Result.candidate_id.in_(candidate_ids))
    )

    if year:
        query = query.filter(models.Election.year == year)

    results = query.order_by(models.Election.year.desc(), models.Result.result_id).all()
    if not results:
        logger.info(f"No result rows found for candidate_ids={candidate_ids} with year={year}")
        return None

    items: List[dict] = []
    for result in results:
        cand = result.candidate
        party = cand.party if cand else None
        election = result.election
        constituency = election.constituency if election else None
        state = constituency.state if constituency else None

        # Build election_year mapping with string keys (keeps JSON consistent)
        election_year_map = { str(cid): years_by_candidate.get(cid, []) for cid in candidate_ids }

        item = {
            "state_name": state.state_name if state else None,
            "pc_name": constituency.pc_name if constituency else None,
            "candidate_name": cand.candidate_name if cand else None,
            "sex": cand.gender if cand else None,
            "age": cand.age if cand else None,
            "category": cand.category if cand else None,
            "party_name": party.party_name if party else None,
            "party_symbol": party.party_symbol if party else None,
            "general_votes": result.general_votes,
            "postal_votes": result.postal_votes,
            "total_votes": result.total_votes,
            "total_electors": constituency.total_electors if constituency else None,
            "year": election.year if election else None,
            "status": "inactive" if result.is_deleted else "active",
            "verification_status": result.verification_status,
            "election_year": election_year_map,
        }
        items.append(item)

    logger.info(f"Returning {len(items)} rows for candidate_name='{candidate_name}' with election_year mapping keys={list(years_by_candidate.keys())}")
    return items
    
def update_election_service_by_candidate(
    db: Session,
    candidate_id: int,
    payload,
    election_id: Optional[int] = None,
    update_all: bool = False,
    role:Optional[str] = None
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

        if "status" in data:
            result.is_deleted = False if data['status'] == "active" else True
        if role =="employee":
            result.verification_status == "under_review"
        else:
            result.verification_status == "verified_admin"
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
        
# def get_candidate_history(db, affidavit):
#     """
#     Optimized: Find how many times the candidate has stood in elections
#     for the same PC (pc_name), considering age difference <= 5 years.
#     """

#     # Pre-trim + lowercase target name
#     target_name = affidavit.candidate_name.strip().lower()
#     target_age = float(affidavit.age or 0)

#     # Fetch only needed fields (avoid loading big rows)
#     all_affidavits = (
#     db.query(
#         models.Affidavit.candidate_name,
#         models.Affidavit.age,
#         models.Affidavit.year
#     )
#     .filter(models.Affidavit.pc_name.ilike(affidavit.pc_name.strip()))
#     .filter(func.similarity(models.Affidavit.candidate_name, affidavit.candidate_name) > 0.4)  
#     .all()
# )

#     # Use set for unique storage
#     candidate_years = set()
#     candidate_aliases = set()

#     # Batch fuzzy match using process.extract instead of per-loop fuzz
#     # (much faster than calling fuzz.token_sort_ratio individually)
#     names = [a.candidate_name.strip().lower() for a in all_affidavits]
#     matches = process.extract(
#         target_name,
#         names,
#         scorer=fuzz.token_sort_ratio,
#         score_cutoff=80  # skip bad matches quickly
#     )

#     # Map matched names back to original rows
#     matched_names = set([m[0] for m in matches])

#     for aff in all_affidavits:
#         cand_name = aff.candidate_name.strip().lower()
#         if cand_name in matched_names:
#             try:
#                 age_diff = abs(target_age - float(aff.age or 0))
#             except Exception:
#                 age_diff = 0
#             if age_diff <= 5:
#                 candidate_aliases.add(aff.candidate_name.strip())
#                 if aff.year:
#                     candidate_years.add(int(aff.year))

#     return {
#         "times_stood": len(candidate_years),
#         "years": sorted(candidate_years),
#         "aliases": sorted(candidate_aliases),
#     }

def get_candidate_history(db: Session, affidavit):
    target_name = affidavit.candidate_name.strip().lower()
    target_age = float(affidavit.age or 0)

    all_affidavits = (
        db.query(
            models.Affidavit.candidate_name,
            models.Affidavit.age,
            models.Affidavit.year,
        )
        .filter(models.Affidavit.pc_name.ilike(affidavit.pc_name.strip()))
        .filter(func.similarity(models.Affidavit.candidate_name, affidavit.candidate_name) > 0.4)
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

class _DictPayloadWrapper:
    """Tiny wrapper so controller can call payload.dict(exclude_unset=True)."""
    def __init__(self, data: Dict):
        self._data = data

    def dict(self, exclude_unset: bool = True) -> Dict:
        # ignore exclude_unset because we already prepared data accordingly
        return self._data
