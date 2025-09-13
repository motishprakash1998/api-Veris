# src/routers/election_services/controller.py
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from .models import eci as models

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
