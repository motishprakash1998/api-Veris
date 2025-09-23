from sqlalchemy import  func ,case
from sqlalchemy.orm import Session,joinedload
from .schemas import  CommonFilters
from src.routers.employees.models import  Employee ,EmployeeProfile, StatusEnum
from src.routers.election_services.models import  Affidavit,Result,Election,Candidate,Constituency,Party,State
from loguru import  logger
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_

def get_employee_counts(db: Session, filters: CommonFilters):
    query = (
        db.query(
            func.count(Employee.id).label("total_employees"),
            func.sum(case((Employee.status == StatusEnum.active, 1), else_=0)).label("active_employees"),
            func.sum(case((Employee.status == StatusEnum.inactive, 1), else_=0)).label("inactive_employees"),
            func.sum(case((Employee.status == StatusEnum.waiting, 1), else_=0)).label("waiting_employees"),
        )
        .join(EmployeeProfile, EmployeeProfile.employee_id == Employee.id)
    )

    if filters.state_name:
        query = query.filter(EmployeeProfile.state_name == filters.state_name)
    if filters.pc_name:
        query = query.filter(EmployeeProfile.pc_name == filters.pc_name)
    if filters.year:
        query = query.filter(func.extract("year", Employee.created_at) == filters.year)

    result = query.first()
    logger.error(f"Result is :{result}")
    data = {
        "total_employees": result.total_employees,
        "active_employees": result.active_employees,
        "inactive_employees": result.inactive_employees,
        "waiting_employees": result.waiting_employees,
    }
    logger.info(f"Data in the result is :{data}")

    return data
# -------------------------
# Get ECI Data
# -------------------------
def get_eci_data(db: Session, filters: CommonFilters):
    query = (
        db.query(Result)
        .join(Result.election)
        .join(Election.constituency)
        .join(Constituency.state)
        .join(Result.candidate)
        .join(Candidate.party)
        .options(
            joinedload(Result.election).joinedload(Election.constituency).joinedload(Constituency.state),
            joinedload(Result.candidate).joinedload(Candidate.party),
        )
        .filter(Result.is_deleted == False)  # exclude soft-deleted
    )

    # Apply filters
    if filters.state_name:
        query = query.filter(State.state_name == filters.state_name)
    if filters.pc_name:
        query = query.filter(Constituency.pc_name == filters.pc_name)
    if filters.year:
        query = query.filter(Election.year == filters.year)
    if filters.party_name:
        query = query.filter(Party.party_name == filters.party_name)
    if filters.candidate_name:
        query = query.filter(Candidate.candidate_name == filters.candidate_name)

    return query.all()


# -------------------------
# Get MyNeta Data (Affidavits)
# -------------------------
def get_myneta_data(db: Session, filters: CommonFilters):
    query = db.query(Affidavit)

    # Apply filters
    if filters.state_name:
        query = query.filter(Affidavit.state_name == filters.state_name)
    if filters.pc_name:
        query = query.filter(Affidavit.pc_name == filters.pc_name)
    if filters.year:
        query = query.filter(Affidavit.year == filters.year)
    if filters.party_name:
        query = query.filter(Affidavit.party_name == filters.party_name)
    if filters.candidate_name:
        query = query.filter(Affidavit.candidate_name == filters.candidate_name)

    return query.all()
"""
Dashboard metrics and aggregation functions for admin visualizations — FILTER-AWARE version.

This file extends the prior metrics module to accept a `CommonFilters` object (pydantic)
so the admin dashboard can request filtered analytics (by state, constituency, year,
party, candidate).

Usage (fastapi route):
    from app.database import get_db
    from app.schemas import CommonFilters
    from dashboard_metrics import get_dashboard_data

    @router.get('/dashboard')
    def dashboard(filters: CommonFilters = Depends(), db: Session = Depends(get_db)):
        return get_dashboard_data(db, filters)

Each function accepts a SQLAlchemy `Session` and an optional `filters: CommonFilters`.
They return JSON-serializable primitives suitable for charting on the frontend.
"""
# from typing import List, Dict, Any, Optional
# from sqlalchemy.orm import Session
# from sqlalchemy import func, desc, and_, or_
# import logging

# # import your models and filter schema
# from app.models import State, Constituency, Party, Candidate, Election, Result
# from app.schemas import CommonFilters

# logger = logging.getLogger(__name__)


# -------------------------
# Helper: build SQLAlchemy filter expressions from CommonFilters
# -------------------------

def _apply_filters_to_query(query, filters: Optional[CommonFilters]):
    """Given a SQLAlchemy query, apply WHERE filters based on CommonFilters.

    NOTE: This function assumes the query already joined the relevant tables where
    the filter columns live (state, constituency, election, party, candidate).
    It returns the modified query.
    """
    if not filters:
        return query

    if filters.state_name:
        query = query.filter(func.lower(State.state_name) == filters.state_name.strip().lower())
    if filters.pc_name:
        query = query.filter(func.lower(Constituency.pc_name) == filters.pc_name.strip().lower())
    if filters.year:
        query = query.filter(Election.year == filters.year)
    if filters.party_name:
        query = query.filter(func.lower(Party.party_name) == filters.party_name.strip().lower())
    if filters.candidate_name:
        # allow partial matches for candidate name
        name_like = f"%{filters.candidate_name.strip().lower()}%"
        query = query.filter(func.lower(Candidate.candidate_name).like(name_like))
    return query


# -------------------------
# Basic totals (filter-aware)
# -------------------------
def total_counts(session: Session, filters: Optional[CommonFilters] = None) -> Dict[str, int]:
    """Return general totals for dashboard tiles. Filters restrict the counts where applicable."""
    # For overall totals we interpret filters conservatively: when state/pc/year provided
    # we count scoped objects, otherwise full counts.
    if filters and (filters.state_name or filters.pc_name or filters.year or filters.party_name or filters.candidate_name):
        # Count states matching filter (only state_name filter makes sense)
        total_states = 0
        if filters.state_name:
            total_states = session.query(func.count(State.state_id)).filter(func.lower(State.state_name) == filters.state_name.strip().lower()).scalar() or 0
        total_constituencies = session.query(func.count(Constituency.pc_id)).join(State).filter(func.lower(State.state_name) == filters.state_name.strip().lower()) if filters.state_name else session.query(func.count(Constituency.pc_id))
        total_constituencies = total_constituencies.scalar() or 0

        # parties / candidates: apply name filters
        total_parties = session.query(func.count(Party.party_id))
        if filters and filters.party_name:
            total_parties = total_parties.filter(func.lower(Party.party_name) == filters.party_name.strip().lower())
        total_parties = total_parties.scalar() or 0

        total_candidates = session.query(func.count(Candidate.candidate_id))
        if filters and filters.candidate_name:
            total_candidates = total_candidates.filter(func.lower(Candidate.candidate_name).like(f"%{filters.candidate_name.strip().lower()}%"))
        total_candidates = total_candidates.scalar() or 0

        total_elections = session.query(func.count(Election.election_id))
        if filters and filters.year:
            total_elections = total_elections.filter(Election.year == filters.year)
        total_elections = total_elections.scalar() or 0

        return {
            "states": int(total_states),
            "constituencies": int(total_constituencies),
            "parties": int(total_parties),
            "candidates": int(total_candidates),
            "elections": int(total_elections),
        }

    # No filters: simple totals
    total_states = session.query(func.count(State.state_id)).scalar() or 0
    total_constituencies = session.query(func.count(Constituency.pc_id)).scalar() or 0
    total_parties = session.query(func.count(Party.party_id)).scalar() or 0
    total_candidates = session.query(func.count(Candidate.candidate_id)).scalar() or 0
    total_elections = session.query(func.count(Election.election_id)).scalar() or 0

    return {
        "states": total_states,
        "constituencies": total_constituencies,
        "parties": total_parties,
        "candidates": total_candidates,
        "elections": total_elections,
    }


# -------------------------
# Elector counts and turnout (filter-aware)
# -------------------------
def elector_count_by_state(session: Session, filters: Optional[CommonFilters] = None) -> List[Dict[str, Any]]:
    """List of states and elector totals (applies state/pc filters if provided)."""
    q = (
        session.query(State.state_name, func.sum(Constituency.total_electors).label("electors"))
        .join(Constituency, State.state_id == Constituency.state_id)
        .group_by(State.state_id)
        .order_by(desc("electors"))
    )
    # apply state/pc filters via _apply_filters_to_query — ensure joins exist
    q = _apply_filters_to_query(q, filters)
    return [{"state": r.state_name, "electors": int(r.electors or 0)} for r in q]


def turnout_by_state_year(session: Session, filters: Optional[CommonFilters] = None) -> List[Dict[str, Any]]:
    """Turnout percentages per state; if filters.year provided it uses that, else uses filters.year or aggregated."""
    q = (
        session.query(
            State.state_name.label("state"),
            func.sum(Election.total_votes_polled_in_constituency).label("votes_polled"),
            func.sum(Constituency.total_electors).label("electors")
        )
        .join(Constituency, State.state_id == Constituency.state_id)
        .join(Election, Constituency.pc_id == Election.pc_id)
    )
    q = _apply_filters_to_query(q, filters)
    q = q.group_by(State.state_id).order_by(desc("votes_polled"))

    out = []
    for r in q:
        electors = int(r.electors or 0)
        votes = int(r.votes_polled or 0)
        turnout_pct = (votes / electors * 100) if electors > 0 else 0.0
        out.append({"state": r.state, "votes_polled": votes, "electors": electors, "turnout_pct": round(turnout_pct, 2)})
    return out


def turnout_by_constituency_year(session: Session, filters: CommonFilters) -> List[Dict[str, Any]]:
    """Return constituencies' turnout for a specific year. Year must be present in filters.

    If filters.year is not set, returns empty list and logs a warning.
    """
    if not filters or not filters.year:
        logger.warning("turnout_by_constituency_year called without filters.year — returning empty list")
        return []

    year = filters.year
    q = (
        session.query(
            Constituency.pc_id,
            Constituency.pc_name,
            Constituency.total_electors,
            Election.total_votes_polled_in_constituency.label("votes_polled")
        )
        .join(Election, Constituency.pc_id == Election.pc_id)
        .filter(Election.year == year)
    )
    q = _apply_filters_to_query(q, filters)
    q = q.order_by(desc("votes_polled"))

    out = []
    for r in q:
        electors = int(r.total_electors or 0)
        votes = int(r.votes_polled or 0)
        turnout = (votes / electors * 100) if electors > 0 else 0.0
        out.append({"pc_id": r.pc_id, "pc_name": r.pc_name, "electors": electors, "votes_polled": votes, "turnout_pct": round(turnout, 2)})
    return out


# -------------------------
# Seats / winners / vote share (filter-aware)
# -------------------------
def seats_won_by_party_year(session: Session, filters: CommonFilters) -> List[Dict[str, Any]]:
    """Compute seats won by party for filters.year. Year is required in filters.

    Supports scoping by state/pc if provided.
    """
    if not filters or not filters.year:
        logger.warning("seats_won_by_party_year called without year — returning empty list")
        return []
    year = filters.year

    subq = (
        session.query(
            Result.election_id,
            Election.pc_id.label("pc_id"),
            Result.candidate_id,
            Result.total_votes.label("votes")
        )
        .join(Election, Result.election_id == Election.election_id)
        .filter(Election.year == year)
        .subquery()
    )

    max_votes_sq = (
        session.query(subq.c.pc_id, func.max(subq.c.votes).label("max_votes"))
        .group_by(subq.c.pc_id)
        .subquery()
    )

    winners_q = (
        session.query(subq.c.pc_id, subq.c.candidate_id, subq.c.votes)
        .join(max_votes_sq, and_(subq.c.pc_id == max_votes_sq.c.pc_id, subq.c.votes == max_votes_sq.c.max_votes))
        .subquery()
    )

    q = (
        session.query(Party.party_name, func.count().label("seats"))
        .join(Candidate, Candidate.party_id == Party.party_id)
        .join(winners_q, winners_q.c.candidate_id == Candidate.candidate_id)
        .group_by(Party.party_id)
        .order_by(desc("seats"))
    )

    # If filters.state_name provided, we need to join back to Constituency/Election to restrict
    if filters and filters.state_name:
        # re-apply by joining through candidate->result->election->constituency->state
        q = q.join(Candidate).join(Result, Result.candidate_id == Candidate.candidate_id).join(Election, Result.election_id == Election.election_id).join(Constituency, Election.pc_id == Constituency.pc_id).join(State, Constituency.state_id == State.state_id).filter(func.lower(State.state_name) == filters.state_name.strip().lower())

    return [{"party": r.party_name, "seats": int(r.seats)} for r in q]


def winners_by_constituency_year(session: Session, filters: CommonFilters) -> List[Dict[str, Any]]:
    """Return winners per constituency for the provided year (filters.year must be set)."""
    if not filters or not filters.year:
        logger.warning("winners_by_constituency_year called without year — returning empty list")
        return []
    year = filters.year

    res_q = (
        session.query(
            Constituency.pc_id,
            Constituency.pc_name,
            Candidate.candidate_id,
            Candidate.candidate_name,
            Party.party_name,
            Result.total_votes
        )
        .join(Election, Constituency.pc_id == Election.pc_id)
        .join(Result, Result.election_id == Election.election_id)
        .join(Candidate, Candidate.candidate_id == Result.candidate_id)
        .join(Party, Party.party_id == Candidate.party_id)
        .filter(Election.year == year)
        .order_by(Constituency.pc_id, desc(Result.total_votes))
    )

    # apply optional filters
    res_q = _apply_filters_to_query(res_q, filters)

    out = []
    current_pc = None
    winner = None
    runner_up_votes = 0
    for row in res_q:
        pc = row.pc_id
        if pc != current_pc:
            if winner:
                margin = winner["votes"] - runner_up_votes
                out.append({
                    "pc_id": winner["pc_id"],
                    "pc_name": winner["pc_name"],
                    "candidate_id": winner["candidate_id"],
                    "candidate_name": winner["candidate_name"],
                    "party": winner["party"],
                    "votes": winner["votes"],
                    "margin": margin,
                })
            current_pc = pc
            winner = {"pc_id": row.pc_id, "pc_name": row.pc_name, "candidate_id": row.candidate_id, "candidate_name": row.candidate_name, "party": row.party_name, "votes": int(row.total_votes or 0)}
            runner_up_votes = 0
        else:
            if runner_up_votes == 0:
                runner_up_votes = int(row.total_votes or 0)

    if winner:
        margin = winner["votes"] - runner_up_votes
        out.append({
            "pc_id": winner["pc_id"],
            "pc_name": winner["pc_name"],
            "candidate_id": winner["candidate_id"],
            "candidate_name": winner["candidate_name"],
            "party": winner["party"],
            "votes": winner["votes"],
            "margin": margin,
        })

    return out


def top_parties_by_vote_share_year(session: Session, filters: CommonFilters, top_n: int = 10) -> List[Dict[str, Any]]:
    """Return vote share per party for filters.year (year required)."""
    if not filters or not filters.year:
        return []
    year = filters.year

    total_votes = (
        session.query(func.sum(Result.total_votes))
        .join(Election, Result.election_id == Election.election_id)
        .filter(Election.year == year)
        .scalar() or 0
    )

    q = (
        session.query(Party.party_name, func.sum(Result.total_votes).label("votes"))
        .join(Candidate, Candidate.party_id == Party.party_id)
        .join(Result, Result.candidate_id == Candidate.candidate_id)
        .join(Election, Result.election_id == Election.election_id)
        .filter(Election.year == year)
        .group_by(Party.party_id)
        .order_by(desc("votes"))
        .limit(top_n)
    )
    q = _apply_filters_to_query(q, filters)

    out = []
    for r in q:
        votes = int(r.votes or 0)
        share = (votes / total_votes * 100) if total_votes > 0 else 0.0
        out.append({"party": r.party_name, "votes": votes, "vote_share_pct": round(share, 2)})
    return out


# -------------------------
# Candidate-level analytics (filter-aware)
# -------------------------

def gender_distribution(session: Session, filters: Optional[CommonFilters] = None) -> Dict[str, int]:
    """Gender breakdown; if filters.year provided it restricts to contestants in that year."""
    if filters and filters.year:
        q = (
            session.query(Candidate.gender, func.count(func.distinct(Candidate.candidate_id)))
            .join(Result, Candidate.candidate_id == Result.candidate_id)
            .join(Election, Result.election_id == Election.election_id)
            .filter(Election.year == filters.year)
            .group_by(Candidate.gender)
        )
        q = _apply_filters_to_query(q, filters)
    else:
        q = session.query(Candidate.gender, func.count(Candidate.candidate_id)).group_by(Candidate.gender)
        q = _apply_filters_to_query(q, filters)

    res = {"male": 0, "female": 0, "other": 0, "unknown": 0}
    for gender, count in q:
        g = (gender or "unknown").strip().lower()
        if g in ("m", "male"):
            res["male"] += int(count or 0)
        elif g in ("f", "female"):
            res["female"] += int(count or 0)
        elif g:
            res["other"] += int(count or 0)
        else:
            res["unknown"] += int(count or 0)
    return res


def average_age_by_party(session: Session, filters: Optional[CommonFilters] = None) -> List[Dict[str, Any]]:
    """Average candidate age by party optionally filtered by year/state/pc."""
    if filters and filters.year:
        q = (
            session.query(Party.party_name, func.avg(Candidate.age).label("avg_age"))
            .join(Candidate, Candidate.party_id == Party.party_id)
            .join(Result, Result.candidate_id == Candidate.candidate_id)
            .join(Election, Result.election_id == Election.election_id)
            .filter(Election.year == filters.year)
            .group_by(Party.party_id)
            .order_by(desc("avg_age"))
        )
        q = _apply_filters_to_query(q, filters)
    else:
        q = (
            session.query(Party.party_name, func.avg(Candidate.age).label("avg_age"))
            .join(Candidate, Candidate.party_id == Party.party_id)
            .group_by(Party.party_id)
            .order_by(desc("avg_age"))
        )
        q = _apply_filters_to_query(q, filters)

    return [{"party": r.party_name, "avg_age": round(float(r.avg_age or 0), 2)} for r in q]


def candidate_count_per_pc(session: Session, filters: Optional[CommonFilters] = None) -> List[Dict[str, Any]]:
    """Number of candidates per constituency; supports filtering by year/state/pc."""
    q = (
        session.query(Constituency.pc_id, Constituency.pc_name, func.count(Result.result_id).label("candidates"))
        .join(Election, Constituency.pc_id == Election.pc_id)
        .join(Result, Result.election_id == Election.election_id)
    )
    q = _apply_filters_to_query(q, filters)
    q = q.group_by(Constituency.pc_id).order_by(desc("candidates"))
    return [{"pc_id": r.pc_id, "pc_name": r.pc_name, "candidates": int(r.candidates)} for r in q]


def close_margins(session: Session, filters: CommonFilters, top_n: int = 10) -> List[Dict[str, Any]]:
    """Top-N smallest winning margins for filters.year (year required)."""
    winners = winners_by_constituency_year(session, filters)
    sorted_close = sorted(winners, key=lambda x: x.get("margin", 0))[:top_n]
    return sorted_close


# -------------------------
# Higher-level payload builder and controller
# -------------------------
def build_dashboard_payload(session: Session, filters: Optional[CommonFilters] = None) -> Dict[str, Any]:
    """Assemble a dashboard payload using filter-aware helpers.

    If filters.year is present, year-specific datasets are included.
    """
    payload = {
        "totals": total_counts(session, filters),
        "elector_by_state": elector_count_by_state(session, filters),
        "gender_distribution": gender_distribution(session, filters),
        "candidate_count_per_pc": candidate_count_per_pc(session, filters),
        "average_age_by_party": average_age_by_party(session, filters),
    }

    if filters and filters.year:
        payload.update({
            "turnout_by_state": turnout_by_state_year(session, filters),
            "turnout_by_constituency": turnout_by_constituency_year(session, filters),
            "top_parties_by_vote_share": top_parties_by_vote_share_year(session, filters, top_n=10),
            "winners_by_pc": winners_by_constituency_year(session, filters),
            "close_margins": close_margins(session, filters, top_n=10),
            "seats_by_party": seats_won_by_party_year(session, filters),
        })

    return payload


# # affidavit_metrics.py
# from typing import Dict, List, Any, Optional, Tuple
# from sqlalchemy.orm import Session
# from sqlalchemy import func, desc, and_
# import logging

# from app.models import Affidavit  # your model defined above
# from app.schemas import CommonFilters

# logger = logging.getLogger(__name__)


# -------------------------
# Helper: apply simple CommonFilters to Affidavit queries
# -------------------------
def _apply_affidavit_filters(q, filters: Optional[CommonFilters]):
    """Apply CommonFilters to a query on Affidavit (State/PC/Year/Party/Candidate)."""
    if not filters:
        return q
    if filters.state_name:
        q = q.filter(func.lower(Affidavit.state_name) == filters.state_name.strip().lower())
    if filters.pc_name:
        q = q.filter(func.lower(Affidavit.pc_name) == filters.pc_name.strip().lower())
    if filters.year:
        q = q.filter(Affidavit.year == filters.year)
    if filters.party_name:
        q = q.filter(func.lower(Affidavit.party_name) == filters.party_name.strip().lower())
    if filters.candidate_name:
        q = q.filter(func.lower(Affidavit.candidate_name).like(f"%{filters.candidate_name.strip().lower()}%"))
    return q


# -------------------------
# Tile metrics
# -------------------------
def affidavit_totals(session: Session, filters: Optional[CommonFilters] = None) -> Dict[str, int]:
    """
    Return quick totals useful for dashboard tiles:
      - total_records
      - with_criminal_cases
      - with_assets_reported
    """
    base_q = session.query(func.count(Affidavit.affidavit_id))
    base_q = _apply_affidavit_filters(base_q, filters)
    total = int(base_q.scalar() or 0)

    criminal_q = session.query(func.count(Affidavit.affidavit_id)).filter(Affidavit.criminal_cases > 0)
    criminal_q = _apply_affidavit_filters(criminal_q, filters)
    with_criminal = int(criminal_q.scalar() or 0)

    assets_q = session.query(func.count(Affidavit.affidavit_id)).filter(Affidavit.total_assets.isnot(None))
    assets_q = _apply_affidavit_filters(assets_q, filters)
    with_assets = int(assets_q.scalar() or 0)

    return {
        "total_records": total,
        "with_criminal_cases": with_criminal,
        "with_assets_reported": with_assets,
    }


# -------------------------
# Top / ranking analytics
# -------------------------
def top_candidates_by_assets(session: Session, filters: Optional[CommonFilters] = None, top_n: int = 10) -> List[Dict[str, Any]]:
    """
    Top-N candidates by declared total_assets (desc). Returns:
      [{candidate_name, party_name, state_name, pc_name, year, total_assets}]
    """
    q = (
        session.query(
            Affidavit.candidate_name,
            Affidavit.party_name,
            Affidavit.state_name,
            Affidavit.pc_name,
            Affidavit.year,
            Affidavit.total_assets
        )
        .filter(Affidavit.total_assets.isnot(None))
    )

    # <-- Apply filters before ordering/limiting
    q = _apply_affidavit_filters(q, filters)

    q = q.order_by(desc(Affidavit.total_assets)).limit(top_n)
    return [
        {
            "candidate_name": r.candidate_name,
            "party_name": r.party_name,
            "state_name": r.state_name,
            "pc_name": r.pc_name,
            "year": r.year,
            "total_assets": int(r.total_assets) if r.total_assets is not None else None,
        }
        for r in q
    ]


def top_candidates_by_liabilities(session: Session, filters: Optional[CommonFilters] = None, top_n: int = 10) -> List[Dict[str, Any]]:
    """Top-N by liabilities (desc)."""
    q = (
        session.query(
            Affidavit.candidate_name,
            Affidavit.party_name,
            Affidavit.state_name,
            Affidavit.pc_name,
            Affidavit.year,
            Affidavit.liabilities
        )
        .filter(Affidavit.liabilities.isnot(None))
    )

    q = _apply_affidavit_filters(q, filters)
    q = q.order_by(desc(Affidavit.liabilities)).limit(top_n)
    return [
        {
            "candidate_name": r.candidate_name,
            "party_name": r.party_name,
            "state_name": r.state_name,
            "pc_name": r.pc_name,
            "year": r.year,
            "liabilities": int(r.liabilities) if r.liabilities is not None else None,
        }
        for r in q
    ]


# -------------------------
# Aggregations and distributions
# -------------------------
def criminal_cases_summary(session: Session, filters: Optional[CommonFilters] = None) -> Dict[str, Any]:
    """
    Summary counts for criminal case buckets:
      - total_with_cases
      - average_cases
      - top offenders (candidates with highest number of cases)
    """
    # total records (filter-aware)
    base = session.query(func.count(Affidavit.affidavit_id)).select_from(Affidavit)
    base = _apply_affidavit_filters(base, filters)
    total = int(base.scalar() or 0)

    # with cases
    with_cases_q = session.query(func.count(Affidavit.affidavit_id)).select_from(Affidavit).filter(Affidavit.criminal_cases > 0)
    with_cases_q = _apply_affidavit_filters(with_cases_q, filters)
    with_cases = int(with_cases_q.scalar() or 0)

    # average cases (filter-aware)
    avg_cases_q = session.query(func.avg(Affidavit.criminal_cases)).select_from(Affidavit)
    avg_cases_q = _apply_affidavit_filters(avg_cases_q, filters)
    avg = float(avg_cases_q.scalar() or 0.0)

    # Top offenders - BUILD base query, APPLY filters, THEN order/limit
    top_offenders_q = (
        session.query(
            Affidavit.candidate_name,
            Affidavit.party_name,
            Affidavit.state_name,
            Affidavit.pc_name,
            Affidavit.year,
            Affidavit.criminal_cases
        )
        .filter(Affidavit.criminal_cases.isnot(None))
    )

    # IMPORTANT: apply filters BEFORE order_by/limit
    top_offenders_q = _apply_affidavit_filters(top_offenders_q, filters)

    top_offenders_q = top_offenders_q.order_by(desc(Affidavit.criminal_cases)).limit(10)

    top_offenders = top_offenders_q.all()

    return {
        "total_records": total,
        "with_criminal_cases": with_cases,
        "average_criminal_cases": round(avg, 2),
        "top_offenders": [
            {
                "candidate_name": r.candidate_name,
                "party_name": r.party_name,
                "state_name": r.state_name,
                "pc_name": r.pc_name,
                "year": r.year,
                "criminal_cases": int(r.criminal_cases or 0),
            }
            for r in top_offenders
        ],
    }


def education_level_distribution(session: Session, filters: Optional[CommonFilters] = None) -> List[Dict[str, Any]]:
    """
    Returns counts per education level string. Useful for a bar chart.
    Output: [{education, count}]
    """
    q = session.query(Affidavit.education, func.count(Affidavit.affidavit_id).label("cnt")).group_by(Affidavit.education).order_by(desc("cnt"))
    q = _apply_affidavit_filters(q, filters)
    return [{"education": r.education or "Unknown", "count": int(r.cnt)} for r in q]


def age_distribution(session: Session, filters: Optional[CommonFilters] = None, bins: Optional[List[Tuple[int, int]]] = None) -> List[Dict[str, Any]]:
    """
    Simple age histogram aggregated into bins.
    bins: list of (low_inclusive, high_inclusive) pairs, default example below.
    Returns: [{bin_label, count, min, max}]
    """
    if bins is None:
        bins = [(18, 30), (31, 40), (41, 50), (51, 60), (61, 120)]

    results = []
    for low, high in bins:
        q = session.query(func.count(Affidavit.affidavit_id)).filter(Affidavit.age >= low).filter(Affidavit.age <= high)
        q = _apply_affidavit_filters(q, filters)
        cnt = int(q.scalar() or 0)
        results.append({"bin": f"{low}-{high}", "count": cnt, "min": low, "max": high})
    return results


# -------------------------
# Search / table / recent
# -------------------------
def recent_affidavits(session: Session, filters: Optional[CommonFilters] = None, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """Return latest affidavits matching filters (ordered by year desc then id). Useful for admin tables."""
    q = session.query(Affidavit).order_by(desc(Affidavit.year), desc(Affidavit.affidavit_id))

    # Apply filters BEFORE limit/offset
    q = _apply_affidavit_filters(q, filters)

    q = q.limit(limit).offset(offset)
    rows = q.all()
    return [
        {
            "affidavit_id": r.affidavit_id,
            "candidate_name": r.candidate_name,
            "party_name": r.party_name,
            "state_name": r.state_name,
            "pc_name": r.pc_name,
            "year": r.year,
            "age": float(r.age) if r.age is not None else None,
            "criminal_cases": int(r.criminal_cases or 0),
            "total_assets": int(r.total_assets) if r.total_assets is not None else None,
            "liabilities": int(r.liabilities) if r.liabilities is not None else None,
            "candidate_link": r.candidate_link,
            "candidate_history": r.candidate_history,
        }
        for r in rows
    ]


# -------------------------
# Higher-level payload builder
# -------------------------
def build_affidavit_payload(session: Session, filters: Optional[CommonFilters] = None) -> Dict[str, Any]:
    """
    Assemble a JSON-serializable payload tailored for the admin UI.
    Keys:
      - totals
      - top_by_assets
      - top_by_liabilities
      - criminal_summary
      - education_distribution
      - age_distribution
      - recent_affidavits (first page)
    """
    payload = {
        "totals": affidavit_totals(session, filters),
        "top_by_assets": top_candidates_by_assets(session, filters, top_n=10),
        "top_by_liabilities": top_candidates_by_liabilities(session, filters, top_n=10),
        "criminal_summary": criminal_cases_summary(session, filters),
        "education_distribution": education_level_distribution(session, filters),
        "age_distribution": age_distribution(session, filters),
        "recent_affidavits": recent_affidavits(session, filters, limit=50, offset=0),
    }
    return payload


def get_dashboard_data(db: Session, filters: CommonFilters,role:Optional[str]=None):
    """Top-level function used by FastAPI route. Returns combined datasets.

    Response keys:
      - eci_data: main election analytics payload
      - employee_data: wrapper for employee counts (if applicable)
    """
    try:
        if role != "employee":
            employee_data = get_employee_counts(db, filters) or {}
        else:
            employee_data = {}
        eci_data = build_dashboard_payload(db, filters)
        my_neta_dtaa = build_affidavit_payload(db, filters) or {}

        response = {
            "eci_data": eci_data or {},
            "my_neta": my_neta_dtaa or {}
        }

        if role.lower() != "employee":
            response["employee_data"] = employee_data or {}

        logger.debug("Dashboard payload built successfully")
        return response
    except Exception as e:
        logger.exception("Failed to build dashboard data: %s", e)
        return {"eci_data": {}, "employee_data": {}}


# def get_dashboard_data(db: Session, filters: CommonFilters):
#     active_employees = get_employee_counts(db, filters)
#     eci_data = build_dashboard_payload(db,filters)
#     # waiting_employees = get_waiting_employee_data(db, filters)
#     # eci_results = get_eci_data(db, filters)
#     # myneta_affidavits = get_myneta_data(db, filters)
    
#     response = {
#         "eci_data": eci_data or [],
#         # "myneta_data": myneta_affidavits or [],
#         "employee_data": active_employees or {},
#         # "waiting_employee_data": waiting_employees or []
#     }
#     logger.error(f"Response is :{response}")
#     return response

