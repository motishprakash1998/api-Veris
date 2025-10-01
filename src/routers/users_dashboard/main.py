from typing import List, Optional, Dict, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from decimal import Decimal

from src.routers.users_dashboard.models.users import (
    AssemblyState as ST,
    AssemblyParty as PT,
    AssemblyElection as EL,
    AssemblyElectionPartyResult as EPR,
    AssemblyElectionSummary as SUM,
)
from .schemas.users import (
    PartyOut, OppositionTrackOut, WinningProbabilityOut, Section1Out, NextExpectedWin,
    RecentPerformanceItem,  # ensure this exists in your schemas as shown earlier
)
from src.database.db import get_db

router = APIRouter(prefix="/api/users_dashboard", tags=["Users Dashboard"], responses={404: {"description": "Not found"}})

# ---------- helpers (pure functions) ----------
def _merge_code(sn: str) -> str:
    return "BJP" if sn in ("BJP", "JNP") else sn

def _allocate_seats_from_probs(prob_map: List[Tuple[str, float]], total_seats: int) -> Dict[str, int]:
    """Largest remainder method; ensures sum == total_seats."""
    quotas = {k: (p / 100.0) * total_seats for k, p in prob_map}
    floors = {k: int(quotas[k]) for k in quotas}
    rema = {k: quotas[k] - floors[k] for k in quotas}
    used = sum(floors.values())
    left = total_seats - used
    for k, _r in sorted(rema.items(), key=lambda x: x[1], reverse=True)[:left]:
        floors[k] += 1
    return floors

def _party_obj_by_sn(db: Session, counts_rows, sn: str) -> PartyOut:
    # Prefer canonical party row if present in counts; else lookup by short_name
    for (pid, csn, cfn, _w) in counts_rows:
        if _merge_code(csn) == sn:
            return PartyOut(id=pid, short_name=sn, full_name=cfn)
    row = db.execute(select(PT.id, PT.full_name).where(PT.short_name == sn)).first()
    if row:
        return PartyOut(id=row[0], short_name=sn, full_name=row[1])
    return PartyOut(id=0, short_name=sn, full_name=None)

def _recent_performance(db: Session, state: str, etype: str, limit_years: int = 5) -> List[RecentPerformanceItem]:
    rn = func.row_number().over(partition_by=EPR.election_id, order_by=(EPR.seats_won.desc(), EPR.vote_percent.desc(), EPR.party_id.asc()))
    q = (
        select(EL.year, PT.id, PT.short_name, PT.full_name, EPR.seats_won, rn.label("rn"))
        .join(EL, EL.id == EPR.election_id)
        .join(ST, ST.id == EL.state_id)
        .join(PT, PT.id == EPR.party_id)
        .where(ST.name == state, EL.election_type == etype)
        .order_by(EL.year.desc(), EPR.seats_won.desc())
    )
    rows = db.execute(q).all()
    per_year = {}
    for year, pid, sn, fn, seats, rrn in rows:
        y = int(year)
        item = {"party": PartyOut(id=pid, short_name=_merge_code(sn), full_name=fn), "seats": int(seats)}
        if rrn == 1:
            per_year[y] = {"winner": item}
        elif rrn == 2:
            per_year.setdefault(y, {})
            per_year[y]["runner"] = item
    years = sorted(per_year.keys(), reverse=True)[:limit_years]
    out: List[RecentPerformanceItem] = []
    for y in sorted(years):  # ascending for bar chart left→right
        w = per_year[y].get("winner")
        r = per_year[y].get("runner")
        if not w:
            continue
        out.append(
            RecentPerformanceItem(
                year=y,
                winner=w["party"],
                winner_seats=w["seats"],
                runner_up=r["party"] if r else None,
                runner_up_seats=r["seats"] if r else None,
            )
        )
    return out

def _last_election_seats_for(db: Session, state: str, etype: str, year: int, sn_merged: str) -> int:
    """Return seats in *latest* election for merged party code (BJP includes JNP)."""
    q = (
        select(PT.short_name, EPR.seats_won)
        .join(EPR, EPR.party_id == PT.id)
        .join(EL, EL.id == EPR.election_id)
        .join(ST, ST.id == EL.state_id)
        .where(ST.name == state, EL.election_type == etype, EL.year == year)
    )
    total = 0
    for psn, seats in db.execute(q):
        if _merge_code(psn) == sn_merged:
            total += int(seats)
    return total  # handles BJP+JNP combined

@router.get("/party_info", response_model=Section1Out)
def section1(state: str = Query("Rajasthan"), election_type: str = Query("AC"), db: Session = Depends(get_db)):
    # 1) latest election
    latest = db.execute(
        select(EL.id, EL.year, EL.total_seats)
        .join(ST, ST.id == EL.state_id)
        .where(ST.name == state, EL.election_type == election_type)
        .order_by(EL.year.desc()).limit(1)
    ).first()
    if not latest:
        raise HTTPException(404, detail="No elections found for given state and type")
    latest_election_id, latest_year, latest_total_seats = latest
    total_seats = int(latest_total_seats or 200)

    # 2) current ruling party (summary of latest)
    srow = db.execute(
        select(SUM, PT.id, PT.short_name, PT.full_name)
        .select_from(SUM)
        .join(EL, EL.id == SUM.election_id)
        .join(ST, ST.id == EL.state_id)
        .join(PT, PT.id == SUM.winning_party_id)
        .where(ST.name == state, EL.election_type == election_type, EL.id == latest_election_id)
    ).first()
    if not srow:
        raise HTTPException(500, detail="Missing summary for latest election")
    current_party = PartyOut(id=srow[1], short_name=_merge_code(srow[2]), full_name=srow[3])

    # 3) counts by winner across all years (start from summary)
    counts_rows = db.execute(
        select(PT.id, PT.short_name, PT.full_name, func.count().label("wins"))
        .select_from(SUM)
        .join(EL, EL.id == SUM.election_id)
        .join(ST, ST.id == EL.state_id)
        .join(PT, PT.id == SUM.winning_party_id)
        .where(ST.name == state, EL.election_type == election_type)
        .group_by(PT.id, PT.short_name, PT.full_name)
        .order_by(func.count().desc(), PT.short_name.asc())
    ).all()

    # merge JNP->BJP counts
    merged_counts: Dict[str, int] = {}
    for pid, sn, _fn, wins in counts_rows:
        key = _merge_code(sn)
        merged_counts[key] = merged_counts.get(key, 0) + int(wins)

    ruling_sn_merged = current_party.short_name
    ruling_track_count = merged_counts.get(ruling_sn_merged, 0)

    # 4) Total governments
    total_governments = int(db.execute(
        select(func.count()).select_from(EL).join(ST, ST.id == EL.state_id).where(ST.name == state, EL.election_type == election_type)
    ).scalar() or 0)

    # 5) Opposition track record (merged)
    def party_obj(sn: str) -> PartyOut:
        return _party_obj_by_sn(db, counts_rows, sn)
    opposition: List[OppositionTrackOut] = [
        OppositionTrackOut(party=party_obj(sn), governments=w)
        for sn, w in sorted(merged_counts.items(), key=lambda x: (-x[1], x[0]))
        if sn != ruling_sn_merged
    ]

    success_rate_pct = round((ruling_track_count / total_governments) * 100, 2) if total_governments else 0.0
    next_election_year = int(latest_year) + 5

    # 6) Recent performance (last 5)
    recent_performance = _recent_performance(db, state, election_type, limit_years=5)

    # 7) Dynamic probabilities
    # base: historical share (merged)
    bjp_wins = merged_counts.get("BJP", 0)
    inc_wins = merged_counts.get("INC", 0)
    others_wins = total_governments - (bjp_wins + inc_wins)

    if total_governments > 0:
        base_bjp = bjp_wins / total_governments
        base_inc = inc_wins / total_governments
    else:
        base_bjp = base_inc = 0.0
    base_oth = max(0.0, 1.0 - (base_bjp + base_inc))  # whatever remains

    # anti-incumbency bonus: shift 10% from current to main opponent
    bonus = 0.10
    if ruling_sn_merged == "BJP":
        base_inc += bonus
    elif ruling_sn_merged == "INC":
        base_bjp += bonus

    # minimum floor for Others = 0.03
    floor_oth = 0.03
    # normalize to 1.0 after applying floor
    s = base_bjp + base_inc + base_oth
    if s == 0:
        base_bjp, base_inc, base_oth = 0.48, 0.49, 0.03  # fallback
    else:
        base_bjp, base_inc, base_oth = base_bjp/s, base_inc/s, base_oth/s

    # enforce Others floor & renormalize
    base_oth = max(base_oth, floor_oth)
    rem = 1.0 - base_oth
    # split remainder proportionally between BJP/INC
    denom = (base_bjp + base_inc) or 1.0
    base_bjp = rem * (base_bjp / denom)
    base_inc = rem * (base_inc / denom)

    prob_bjp = round(base_bjp * 100, 2)
    prob_inc = round(base_inc * 100, 2)
    prob_oth = round(100.0 - prob_bjp - prob_inc, 2)

    # 8) Seats allocation from probabilities (exactly = total_seats)
    seat_alloc = _allocate_seats_from_probs([("INC", prob_inc), ("BJP", prob_bjp), ("OTHERS", prob_oth)], total_seats)
    inc_seats = seat_alloc["INC"]
    bjp_seats = seat_alloc["BJP"]
    oth_seats = seat_alloc["OTHERS"]

    # seat_change vs latest election seats
    last_inc = _last_election_seats_for(db, state, election_type, int(latest_year), "INC")
    last_bjp = _last_election_seats_for(db, state, election_type, int(latest_year), "BJP")
    last_oth = total_seats - (last_inc + last_bjp)

    inc_change = inc_seats - last_inc
    bjp_change = bjp_seats - last_bjp
    oth_change = oth_seats - last_oth

    # party objs
    inc = party_obj("INC")
    bjp = party_obj("BJP")
    oth = PartyOut(id=0, short_name="OTHERS", full_name="Others")

    # predicted winner = higher probability
    predicted_winner = inc if prob_inc >= prob_bjp and prob_inc >= prob_oth else (bjp if prob_bjp >= prob_oth else oth)
    predicted_confidence_pct = max(prob_inc, prob_bjp, prob_oth)

    probs = [
        WinningProbabilityOut(party=inc, probability_pct=prob_inc, projected_seats=inc_seats, seat_change=inc_change),
        WinningProbabilityOut(party=bjp, probability_pct=prob_bjp, projected_seats=bjp_seats, seat_change=bjp_change),
        WinningProbabilityOut(party=None, probability_pct=prob_oth, projected_seats=oth_seats, seat_change=oth_change),
    ]

    next_expected_wins = [
        NextExpectedWin(party=inc, wins_probability_pct=prob_inc, projected_seats=inc_seats, seat_change=inc_change),
        NextExpectedWin(party=bjp, wins_probability_pct=prob_bjp, projected_seats=bjp_seats, seat_change=bjp_change),
        NextExpectedWin(party=oth, wins_probability_pct=prob_oth, projected_seats=oth_seats, seat_change=oth_change),
    ]

    # build opposition track again with merged names (nice to show)
    opposition = [
        OppositionTrackOut(party=party_obj(sn), governments=int(w))
        for sn, w in sorted(merged_counts.items(), key=lambda x: (-x[1], x[0]))
        if sn != ruling_sn_merged
    ]

    return Section1Out(
        state=state,
        election_type=election_type,
        current_ruling_party=current_party,
        current_ruling_year=int(latest_year),

        ruling_party_track_record_count=int(ruling_track_count),
        total_governments=int(total_governments),
        opposition_track_record=opposition,

        total_terms_current_ruling=int(ruling_track_count),
        success_rate_pct=round(success_rate_pct, 2),
        next_election_year=int(next_election_year),

        recent_performance=recent_performance,

        predicted_winner=predicted_winner,
        predicted_confidence_pct=predicted_confidence_pct,

        winning_probabilities=probs,
        next_expected_wins=next_expected_wins,
    )
