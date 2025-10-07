from typing import List, Optional, Dict, Tuple
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func,distinct
from sqlalchemy.orm import Session, selectinload
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

from src.routers.users_dashboard.models.lokh_sabha import LokhSabhaResult
from src.routers.users_dashboard.schemas import lokh_sabha as lokh_sabha_schemas
from src.routers.users_dashboard.schemas.social_info import SocialInfoResponse, SocialAccountSchema, AccountProfileSchema
from src.routers.social_media.models import models
from loguru import logger
from src.routers.users_dashboard import controllers

router = APIRouter(prefix="/api/users_dashboard", 
                   tags=["Users Dashboard"], 
                   responses={404: {"description": "Not found"}})

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

def _recent_performance(db: Session, state: str, etype: str, limit_years: Optional[int] = None) -> List[RecentPerformanceItem]:
    rn = func.row_number().over(
        partition_by=EPR.election_id,
        order_by=(EPR.seats_won.desc(), EPR.vote_percent.desc(), EPR.party_id.asc())
    )
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

    years = sorted(per_year.keys(), reverse=True)
    if limit_years:  # sirf tab apply hoga jab tu chahata hai
        years = years[:limit_years]

    out: List[RecentPerformanceItem] = []
    for y in sorted(years):  # ascending order timeline ke liye
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

# Merge parties (BJP + JNP)
party_merge_map = {
    "JNP": "BJP",
    "Janata Party": "BJP",
    "Janata Party (Secular)": "BJP",
    "Bharatiya Janta Party": "BJP",
}

def normalize_party(party: str) -> str:
    if not party:
        return "OTHERS"
    return party_merge_map.get(party.strip(), party.strip())


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default

def _party_out_from_sn(sn: str) -> PartyOut:
    """
    Try to use your existing helper if present; otherwise construct a minimal PartyOut.
    """
    try:
        # If you have this helper in your codebase:
        # return _party_obj_by_sn(db, [], sn)
        pass
    except Exception:
        pass
    # Fallback: id unknown (0), full_name = short_name for now
    return PartyOut(id=0, short_name=sn, full_name=sn)

def _largest_remainder_allocation(pairs_pct: List[Tuple[str, float]], total_seats: int) -> Dict[str, int]:
    """
    pairs_pct: [("INC", 48.9), ("BJP", 48.1), ("OTHERS", 3.0)]
    Returns integer seat allocation summing to total_seats.
    """
    if total_seats <= 0:
        return {k: 0 for k, _ in pairs_pct}
    quotas = [(k, (p/100.0) * total_seats) for k, p in pairs_pct]
    base = {k: int(q) for k, q in quotas}
    used = sum(base.values())
    remainders = sorted(
        [(k, q - int(q)) for k, q in quotas],
        key=lambda x: (-x[1], x[0])
    )
    for i in range(total_seats - used):
        base[remainders[i % len(remainders)][0]] += 1
    return base

def _yearly_party_seats(db: Session, state: str) -> Dict[int, Dict[str, int]]:
    """
    Returns: {year: {party_sn_merged: seats_in_state_that_year}}
    """
    q = (
        db.query(LokhSabhaResult.year, LokhSabhaResult.party, func.count(LokhSabhaResult.pc_name))
          .filter(LokhSabhaResult.State == state)
          .group_by(LokhSabhaResult.year, LokhSabhaResult.party)
    )
    out: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for year, party, cnt in q.all():
        out[int(year)][normalize_party(party)] += int(cnt or 0)
    return out

def _latest_year_total_seats(db: Session, state: str) -> Tuple[int, int]:
    """
    Returns: (latest_year, total_pc_in_state_that_year)
    """
    latest_year = db.query(func.max(LokhSabhaResult.year)).filter(LokhSabhaResult.State == state).scalar()
    if latest_year is None:
        raise HTTPException(404, detail="No PC results found for the given state")
    total = db.query(func.count(distinct(LokhSabhaResult.pc_name))).filter(
        LokhSabhaResult.State == state,
        LokhSabhaResult.year == latest_year
    ).scalar() or 0
    return int(latest_year), int(total)

def _winner_and_runner_up(seat_map: Dict[str, int]) -> Tuple[str, int, str, int]:
    """
    From {party: seats}, returns (winner_sn, winner_seats, runner_sn, runner_seats)
    """
    if not seat_map:
        return ("OTHERS", 0, "OTHERS", 0)
    sorted_parties = sorted(seat_map.items(), key=lambda x: (-x[1], x[0]))
    w_sn, w_seats = sorted_parties[0]
    r_sn, r_seats = (sorted_parties[1] if len(sorted_parties) > 1 else ("OTHERS", 0))
    return w_sn, int(w_seats), r_sn, int(r_seats)


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
    recent_performance = _recent_performance(db, state, election_type)

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


@router.get("/pc/party_info", response_model=Section1Out)
def pc_section1(state: str = Query("Rajasthan"), db: Session = Depends(get_db)):
    election_type = "PC"   # Lok Sabha indicator

    # --- 1. Latest Election (2024 for Lok Sabha) ---
    latest_year = db.query(func.max(LokhSabhaResult.year))\
                    .filter(LokhSabhaResult.State == state).scalar()
    if not latest_year:
        raise HTTPException(404, "No Lok Sabha elections found")

    latest_election = db.query(LokhSabhaResult.party, func.count(LokhSabhaResult.pc_name))\
                        .filter(LokhSabhaResult.State == state, LokhSabhaResult.year == latest_year)\
                        .group_by(LokhSabhaResult.party).all()

    # normalize & get ruling
    counts = {}
    for party, cnt in latest_election:
        sn = normalize_party(party)
        counts[sn] = counts.get(sn, 0) + cnt

    ruling_party_sn = max(counts, key=counts.get)
    ruling_party = lokh_sabha_schemas.LokhPartyOut(id=1 if ruling_party_sn=="BJP" else 2,
                            short_name=ruling_party_sn,
                            full_name="Bharatiya Janata Party" if ruling_party_sn=="BJP" else "Indian National Congress")

    total_seats = sum(counts.values())

    # --- 2. Historical winners ---
    all_years = db.query(LokhSabhaResult.year, LokhSabhaResult.party, func.count(LokhSabhaResult.pc_name))\
                  .filter(LokhSabhaResult.State == state)\
                  .group_by(LokhSabhaResult.year, LokhSabhaResult.party).all()

    history = {}
    for year, party, cnt in all_years:
        sn = normalize_party(party)
        history.setdefault(year, {})[sn] = cnt

    recent_performance = []
    for y in sorted(history.keys(), reverse=True)[:10]:
        data = history[y]
        if not data: continue
        winner_sn = max(data, key=data.get)
        runner_sn = sorted(data.items(), key=lambda x: x[1], reverse=True)[1][0] if len(data)>1 else "OTHERS"

        recent_performance.append(lokh_sabha_schemas.LokhElectionPerformanceOut(
            year=y,
            winner=lokh_sabha_schemas.LokhPartyOut(id=1 if winner_sn=="BJP" else 2, short_name=winner_sn, full_name="Bharatiya Janata Party" if winner_sn=="BJP" else "Indian National Congress"),
            winner_seats=data[winner_sn],
            runner_up=lokh_sabha_schemas.LokhPartyOut(id=1 if runner_sn=="BJP" else 2, short_name=runner_sn, full_name="Bharatiya Janata Party" if runner_sn=="BJP" else "Indian National Congress"),
            runner_up_seats=data.get(runner_sn,0)
        ))

    # --- 3. Success rate ---
    total_governments = len(history.keys())
    ruling_count = sum(1 for y, d in history.items() if max(d, key=d.get) == ruling_party_sn)
    success_rate_pct = round((ruling_count / total_governments) * 100, 2)

    # --- 4. Predictions (basic heuristic) ---
    prob_bjp = round((history[max(history)]["BJP"]/total_seats)*100 if "BJP" in history[max(history)] else 45,2)
    prob_inc = round((history[max(history)]["INC"]/total_seats)*100 if "INC" in history[max(history)] else 45,2)
    prob_oth = 100 - (prob_bjp+prob_inc)

    probs = [
        lokh_sabha_schemas.LokhWinningProbabilityOut(party=lokh_sabha_schemas.LokhPartyOut(id=2, short_name="INC", full_name="Indian National Congress"), probability_pct=prob_inc, projected_seats=int(prob_inc/100*total_seats), seat_change=0),
        lokh_sabha_schemas.LokhWinningProbabilityOut(party=lokh_sabha_schemas.LokhPartyOut(id=1, short_name="BJP", full_name="Bharatiya Janata Party"), probability_pct=prob_bjp, projected_seats=int(prob_bjp/100*total_seats), seat_change=0),
        lokh_sabha_schemas.LokhWinningProbabilityOut(party=None, probability_pct=prob_oth, projected_seats=int(prob_oth/100*total_seats), seat_change=0)
    ]

    next_expected_wins = [
        lokh_sabha_schemas.LokhNextExpectedWin(party=p.party if p.party else lokh_sabha_schemas.LokhPartyOut(id=0, short_name="OTHERS", full_name="Others"),
                        wins_probability_pct=p.probability_pct,
                        projected_seats=p.projected_seats,
                        seat_change=p.seat_change)
        for p in probs
    ]

    predicted_winner = max(probs, key=lambda x: x.probability_pct).party
    predicted_confidence_pct = max(p.probability_pct for p in probs)

    return lokh_sabha_schemas.LokhSection1Out(
        state=state,
        election_type="PC",
        current_ruling_party=ruling_party,
        current_ruling_year=latest_year,
        ruling_party_track_record_count=ruling_count,
        total_governments=total_governments,
        opposition_track_record=[],  # TODO fill like AC
        total_terms_current_ruling=ruling_count,
        success_rate_pct=success_rate_pct,
        next_election_year=latest_year+5,
        recent_performance=recent_performance,
        predicted_winner=predicted_winner,
        predicted_confidence_pct=predicted_confidence_pct,
        winning_probabilities=probs,
        next_expected_wins=next_expected_wins
    )


@router.get("/social-info")
def get_social_info_merged(db: Session = Depends(get_db)):
    try:
        query = (
            select(models.SocialAccount)
            .options(
                selectinload(models.SocialAccount.platform),
                selectinload(models.SocialAccount.profiles)
            )
        )

        result = db.execute(query)
        accounts = result.scalars().all()

        merged_accounts = {}

        for acc in accounts:
            # username key without spaces, lowercased
            username_key = (acc.username or "").replace(" ", "").lower()

            if username_key not in merged_accounts:
                merged_accounts[username_key] = {
                    "username": acc.username,
                    "display_name": acc.profiles[0].display_name if acc.profiles else None,
                    "platforms": {
                        "instagram": None,
                        "facebook": None
                    }
                }

            # Determine platform name
            platform_name = (acc.platform.display_name.lower() if acc.platform else None)
            if platform_name not in ["instagram", "facebook"]:
                platform_name = None

            # Fill platform data
            if platform_name and acc.profiles:
                profile = acc.profiles[0]
                merged_accounts[username_key]["platforms"][platform_name] = {
                    "profile_url": acc.profile_url,
                    "bio": profile.bio,
                    "website": profile.website,
                    "location": profile.location,
                    "followers": profile.follower_count or 0,
                    "following": profile.following_count or 0,
                    "posts": profile.post_count or 0,
                    "likes": profile.like_count or 0,
                    "profile_image_url": profile.profile_image_url,
                    "retrieved_at": profile.retrieved_at.isoformat() if profile.retrieved_at else None,
                    "source": profile.source,
                }

        return {"social_accounts": list(merged_accounts.values())}

    except Exception as e:
        logger.error(f"Error fetching social info: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
    
# from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
from datetime import datetime

# router = APIRouter()

# dependency from your app:
# from your_project.db import get_db
# from your_project.logging import logger

DEFAULT_LEADERS = [
    "Lal Chand Kataria",
    "Vasundhara Raje",
    "Ashok Gehlot",
    "Bhajanlal sharma",
    "Sachin Pilot",
    "Diya Kumari",
    "Prem Chand Bairwa",
    "Satish Punia",
    "Govind Singh Dotasra",
    "Madan Rathore"
]

def _safe_int(v):
    try:
        return int(v) if v is not None else None
    except:
        return None
    
@router.get("/ranking")
def social_leaders_ranking(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Return ranking info for top leaders with their basic info, parliament, and assembly data.
    """

    leaders = [
        "Lal Chand Kataria",
        "Vasundhara Raje",
        "Ashok Gehlot",
        "Bhajanlal Sharma",
        "Sachin Pilot",
        "Diya Kumari",
        "Prem Chand Bairwa",
        "Satish Poonia",
        "Govind Singh Dotasra",
        "Madan Rathore"
    ]

    results = []

    try:
        for name in leaders:
            try:
                basic_info = controllers.get_basic_info_leader(db, candidate_name=name)
                parliament = controllers.get_parliament_dashboard_data(db, candidate_name=name)
                assembly = controllers.get_assembly_dashboard_data(db, candidate_name=name)
                social_media = controllers.social_media_info(db, display_name=name)

                results.append({
                    "name": name,
                    "basic_info": basic_info,
                    "parliament": parliament,
                    "assembly": assembly,
                    "social_media": social_media
                })

            except Exception as inner_e:
                # Log and continue with others instead of breaking all
                logger.warning(f"Error fetching data for {name}: {inner_e}")
                results.append({
                    "name": name,
                    "basic_info": [],
                    "parliament": [],
                    "assembly": [],
                    "error": str(inner_e)
                })

        response = {"leaders": results}
        logger.info("Leaders ranking response prepared successfully.")
        return response

    except Exception as e:
        logger.error(f"Error fetching leaders ranking: {e}", exc_info=True)
        try:
            db.rollback()
        except Exception as rb:
            logger.exception(f"Rollback failed while handling error in social_leaders_ranking: {rb}")
        raise HTTPException(status_code=500, detail=str(e))


# @router.get("/leaders/batch")
# def get_leaders_batch(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Return full payloads for DEFAULT_LEADERS (10 names).
    Matches by candidate_affidavits.candidate_name OR account_profiles.display_name OR social_accounts.username.
    """
    try:
        names = DEFAULT_LEADERS

        # build dynamic IN placeholders: (:n0, :n1, ...)
        placeholders = ", ".join([f":n{i}" for i in range(len(names))])
        params = {f"n{i}": names[i] for i in range(len(names))}

        # 1) fetch affidavits for these names (exact match)
        affidavit_q = text(f"""
            SELECT candidate_name, affidavit_id, party_name, "year", criminal_cases, total_assets, education
            FROM public.candidate_affidavits
            WHERE candidate_name IN ({placeholders})
            ORDER BY "year" DESC NULLS LAST
        """)
        aff_rows = [dict(r) for r in db.execute(affidavit_q, params).mappings().all()]

        # map by candidate_name
        aff_by_name = {r["candidate_name"]: r for r in aff_rows}

        # 2) parliament and assembly histories (exact match)
        parl_q = text(f"""
            SELECT pc_name as constituency, candidate, party, votes, vote_percent, margin_votes, margin_percent, total_votes_polled_num as total_votes, "year"
            FROM public.parliament_candidate_information
            WHERE candidate IN ({placeholders})
            ORDER BY candidate, "year" DESC NULLS LAST
        """)
        parl_rows = [dict(r) for r in db.execute(parl_q, params).mappings().all()]

        ac_q = text(f"""
            SELECT ac_name as constituency, candidate, party, votes, vote_percent, margin_votes, margin_percent, total_votes_polled_num as total_votes, "year", "position"
            FROM public.assembly_candidate_information
            WHERE candidate IN ({placeholders})
            ORDER BY candidate, "year" DESC NULLS LAST
        """)
        ac_rows = [dict(r) for r in db.execute(ac_q, params).mappings().all()]

        parl_by_candidate = defaultdict(list)
        for r in parl_rows:
            parl_by_candidate[r["candidate"]].append(r)

        ac_by_candidate = defaultdict(list)
        for r in ac_rows:
            ac_by_candidate[r["candidate"]].append(r)

        # 3) social accounts and profiles where display_name OR username matches any name
        # We'll match COALESCE(ap.display_name, sa.username) IN (names)
        social_q = text(f"""
            SELECT sa.id as social_account_id, sa.platform_id, sa.platform_user_id, sa.username, sa.profile_url,
                   ap.display_name, ap.bio, ap.website, ap.profile_image_url, ap.follower_count, ap.following_count,
                   ap.post_count, ap.like_count, ap.retrieved_at, ap.source,
                   COALESCE(NULLIF(ap.display_name,''), sa.username) as match_key
            FROM public.social_accounts sa
            LEFT JOIN public.account_profiles ap ON ap.social_account_id = sa.id
            WHERE COALESCE(NULLIF(ap.display_name,''), sa.username) IN ({placeholders})
        """)
        social_rows = [dict(r) for r in db.execute(social_q, params).mappings().all()]

        social_by_match = defaultdict(list)
        social_ids = []
        for r in social_rows:
            key = r["match_key"]
            social_by_match[key].append(r)
            if r.get("social_account_id"):
                social_ids.append(r["social_account_id"])

        # 4) instagram_posts aggregation per social_account_id (list-of-all + grouped)
        insta_list_q = text(f"""
            SELECT id, social_account_id, shortcode, likes, "comment", display_url, timestamp
            FROM public.instagram_posts
            WHERE social_account_id IN ({', '.join([str(sid) for sid in social_ids])}) 
            ORDER BY social_account_id, timestamp DESC
        """) if social_ids else None

        insta_rows = []
        if social_ids:
            # use mappings
            insta_rows = [dict(r) for r in db.execute(insta_list_q).mappings().all()]

        # build insta aggregation per account and keep the list of all posts per account
        insta_posts_by_account = defaultdict(list)
        insta_agg_by_account = {}
        for r in insta_rows:
            sid = r["social_account_id"]
            insta_posts_by_account[sid].append({
                "id": r.get("id"),
                "shortcode": r.get("shortcode"),
                "likes": int(r.get("likes") or 0),
                "comments": int(r.get("comment") or 0),
                "display_url": r.get("display_url"),
                "timestamp": r.get("timestamp")
            })

        for sid, posts in insta_posts_by_account.items():
            total_likes = sum(p["likes"] for p in posts)
            total_comments = sum(p["comments"] for p in posts)
            post_count = len(posts)
            insta_agg_by_account[sid] = {
                "total_likes": total_likes,
                "total_comments": total_comments,
                "post_count": post_count,
                "avg_likes_per_post": (total_likes / post_count) if post_count > 0 else 0,
                "avg_comments_per_post": (total_comments / post_count) if post_count > 0 else 0,
                "posts": posts  # list of all posts for this account
            }

        # 5) Build final payloads for each name in default order
        results = []
        for name in names:
            aff = aff_by_name.get(name)
            p_hist = []
            for r in parl_by_candidate.get(name, []):
                p_hist.append({
                    "year": _safe_int(r.get("year")),
                    "election_type": "Parliament",
                    "constituency": r.get("constituency"),
                    "party": r.get("party"),
                    "votes_obtained": _safe_int(r.get("votes")),
                    "vote_share_pct": float(r.get("vote_percent")) if r.get("vote_percent") is not None else None,
                    "position": None,
                    "margin": _safe_int(r.get("margin_votes")),
                    "total_votes": _safe_int(r.get("total_votes")),
                    "result": None,
                    "source": None
                })

            a_hist = []
            for r in ac_by_candidate.get(name, []):
                a_hist.append({
                    "year": _safe_int(r.get("year")),
                    "election_type": "Assembly",
                    "constituency": r.get("constituency"),
                    "party": r.get("party"),
                    "votes_obtained": _safe_int(r.get("votes")),
                    "vote_share_pct": float(r.get("vote_percent")) if r.get("vote_percent") is not None else None,
                    "position": _safe_int(r.get("position")),
                    "margin": _safe_int(r.get("margin_votes")),
                    "total_votes": _safe_int(r.get("total_votes")),
                    "result": None,
                    "source": None
                })

            # social profiles for this name
            social_profiles = social_by_match.get(name, [])
            platforms_list = []
            combined_followers = combined_following = combined_posts_field = combined_like_field = 0
            total_inst_likes = total_inst_comments = total_inst_posts = 0

            for sp in social_profiles:
                sid = sp.get("social_account_id")
                acct_agg = insta_agg_by_account.get(sid, {"total_likes":0,"total_comments":0,"post_count":0,"avg_likes_per_post":0,"avg_comments_per_post":0,"posts":[]})
                followers = sp.get("follower_count") or 0
                following = sp.get("following_count") or 0
                posts_field = sp.get("post_count") or 0
                like_field = sp.get("like_count") or 0

                combined_followers += int(followers)
                combined_following += int(following)
                combined_posts_field += int(posts_field)
                combined_like_field += int(like_field)

                total_inst_likes += acct_agg.get("total_likes", 0)
                total_inst_comments += acct_agg.get("total_comments", 0)
                total_inst_posts += acct_agg.get("post_count", 0)

                platforms_list.append({
                    "social_account_id": sid,
                    "platform_id": sp.get("platform_id"),
                    "username": sp.get("username"),
                    "display_name": sp.get("display_name"),
                    "profile_url": sp.get("profile_url"),
                    "bio": sp.get("bio"),
                    "website": sp.get("website"),
                    "profile_image_url": sp.get("profile_image_url"),
                    "followers": int(followers) if followers else None,
                    "following": int(following) if following else None,
                    "posts": int(posts_field) if posts_field else None,
                    "like_field": int(like_field) if like_field else None,
                    "retrieved_at": sp.get("retrieved_at").isoformat() if sp.get("retrieved_at") else None,
                    "source": sp.get("source"),
                    "instagram_agg": acct_agg
                })

            instagram_agg = {
                "total_likes": total_inst_likes,
                "total_comments": total_inst_comments,
                "post_count": total_inst_posts,
                "avg_likes_per_post": (total_inst_likes / total_inst_posts) if total_inst_posts > 0 else 0,
                "avg_comments_per_post": (total_inst_comments / total_inst_posts) if total_inst_posts > 0 else 0,
            }

            payload = {
                "id": (aff.get("candidate_name").lower().replace(" ", "_") if aff else name.lower().replace(" ", "_")),
                "name": aff.get("candidate_name") if aff else name,
                "aliases": [],
                "dob": None,
                "gender": None,
                "photo_url": None,
                "party": {
                    "id": None,
                    "short_name": aff.get("party_name") if aff else None,
                    "full_name": aff.get("party_name") if aff else None
                },
                "current_positions": [],
                "profile": {
                    "summary": None,
                    "education": [aff.get("education")] if aff and aff.get("education") else [],
                    "profession": None,
                    "contact": {"email": None, "phone": None, "office_address": None}
                },
                "parliament": {
                    "constituency": (parl_by_candidate.get(name, [{}])[0].get("constituency") if parl_by_candidate.get(name) else None),
                    "election_history": p_hist,
                    "committee_memberships": [],
                    "parliamentary_performance": {"questions_asked": None, "bills_introduced": None, "attendance_pct": None, "debates_participated": None}
                },
                "assembly": {
                    "constituency": (ac_by_candidate.get(name, [{}])[0].get("constituency") if ac_by_candidate.get(name) else None),
                    "election_history": a_hist,
                    "assembly_performance": {"questions_asked": None, "motions_supported": None, "attendance_pct": None}
                },
                "social_media": {
                    "platforms": platforms_list,
                    "combined_followers": combined_followers if combined_followers > 0 else None,
                    "combined_following": combined_following if combined_following > 0 else None,
                    "combined_posts": combined_posts_field if combined_posts_field > 0 else None,
                    "combined_like_field": combined_like_field if combined_like_field > 0 else None,
                    "instagram_agg": instagram_agg
                },
                "assets_and_liabilities": {
                    "declared_assets": [],
                    "declared_liabilities": [],
                    "total_net_worth": _safe_int(aff.get("total_assets")) if aff else None,
                    "currency": "INR",
                    "affidavit_source_url": None,
                    "last_declared_year": _safe_int(aff.get("year")) if aff and aff.get("year") else None
                },
                "criminal_cases": [],
                "other_metrics": {
                    "public_approval_rating_pct": None,
                    "policy_achievements": [],
                    "media_coverage_score": None,
                    "influence_score": None,
                    "demographic_appeal": {"urban_pct": None, "rural_pct": None, "youth_pct": None, "women_pct": None, "other_segments": {}}
                },
                "custom_inputs": {"notes": None, "tags": []},
                "comparison_ui": {
                    "display_name": aff.get("candidate_name") if aff else name,
                    "display_order": ["rank_overall", "party", "election_history", "social_media", "assets_and_liabilities", "criminal_cases", "other_metrics"],
                    "spec_sheet_keys": ["party", "latest_position", "combined_followers", "total_net_worth", "public_approval_rating_pct", "criminal_cases_count"],
                    "highlight_metrics": ["influence_score", "media_coverage_score", "public_approval_rating_pct"]
                },
                "ranking": {"rank_overall": None, "rank_by_metric": {"influence_score": None, "electability": None, "social_presence": None, "funds": None}},
                "sources": [],
                "last_updated": datetime.utcnow().isoformat() + "Z",
                "data_quality": {"completeness_pct": None, "last_verified": None, "verified_by": None},
                # helper/debug fields
                "_affidavit": aff,
                "_parliament_rows": parl_by_candidate.get(name, []),
                "_assembly_rows": ac_by_candidate.get(name, []),
                "_social_rows": social_by_match.get(name, []),
                "_instagram_posts_by_account": {sid: insta_agg_by_account[sid]["posts"] for sid in insta_agg_by_account if sid in insta_posts_by_account} if insta_posts_by_account else {}
            }

            results.append(payload)

        return {"count": len(results), "leaders": results}

    except Exception as e:
        logger.exception("Error in get_leaders_batch")
        raise HTTPException(status_code=500, detail=str(e))