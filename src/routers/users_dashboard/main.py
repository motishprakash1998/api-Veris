from typing import List, Optional, Dict, Tuple
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func,distinct
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

from src.routers.users_dashboard.models.lokh_sabha import LokhSabhaResult, VidhanSabhaResult

# from .schemas.lokh_sabha import (
#     PartyRepresentation, ConstituencyDetail, RepresentationBreakdown, PartyConstituenciesResponse,ElectionPerformanceOut,YearPerformance, WinningProbabilityOut
# )

from . import schemas  as lokh_sabha_schemas

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


# # --- Current + Predicted Representation Breakdown ---
# @router.get("/representation/breakdown", response_model=RepresentationBreakdown)
# def get_representation_breakdown(db: Session = Depends(get_db)):
#     # CURRENT MPs (year=2024)
#     mp_query = db.query(LokhSabhaResult.party, func.count(LokhSabhaResult.pc_name))\
#                  .filter(LokhSabhaResult.year == 2024)\
#                  .group_by(LokhSabhaResult.party).all()

#     mp_counts, total_mps = {}, 0
#     for party, count in mp_query:
#         norm = normalize_party(party)
#         mp_counts[norm] = mp_counts.get(norm, 0) + count
#         total_mps += count

#     current_mps = [PartyRepresentation(party=p, seats=s, percentage=round(s/total_mps*100,2)) 
#                    for p,s in mp_counts.items()]

#     # CURRENT MLAs (latest assembly year)
#     mla_query = db.query(VidhanSabhaResult.party, func.count(VidhanSabhaResult.ac_name))\
#                   .filter(VidhanSabhaResult.year == 2023)\
#                   .group_by(VidhanSabhaResult.party).all()

#     mla_counts, total_mlas = {}, 0
#     for party, count in mla_query:
#         norm = normalize_party(party)
#         mla_counts[norm] = mla_counts.get(norm, 0) + count
#         total_mlas += count

#     current_mlas = [PartyRepresentation(party=p, seats=s, percentage=round(s/total_mlas*100,2))
#                     for p,s in mla_counts.items()]

#     # --- Predicted MPs & MLAs ---
#     # For now, naive prediction = same as current (can be enhanced with ML or past trend)
#     predicted_mps = current_mps
#     predicted_mlas = current_mlas

#     return RepresentationBreakdown(
#         current_mps=current_mps,
#         current_mlas=current_mlas,
#         predicted_mps=predicted_mps,
#         predicted_mlas=predicted_mlas
#     )


# # --- Constituency Details for a Party ---
# @router.get("/representation/party/{party_name}", response_model=PartyConstituenciesResponse)
# def get_party_constituencies(party_name: str, db: Session = Depends(get_db)):
#     norm_party = normalize_party(party_name)

#     # MPs
#     mp_rows = db.query(LokhSabhaResult).filter(LokhSabhaResult.year == 2024).all()
#     mp_constituencies = [
#         ConstituencyDetail(
#             name=r.pc_name,
#             type=r.pc_type,
#             winning_candidate=r.winning_candidate,
#             party=normalize_party(r.party),
#             margin=float(r.margin_percent)
#         ) for r in mp_rows if normalize_party(r.party) == norm_party
#     ]

#     # MLAs
#     mla_rows = db.query(VidhanSabhaResult).filter(VidhanSabhaResult.year == 2023).all()
#     mla_constituencies = [
#         ConstituencyDetail(
#             name=r.ac_name,
#             type=r.ac_type,
#             winning_candidate=r.winning_candidate,
#             party=normalize_party(r.party),
#             margin=float(r.margin_percent)
#         ) for r in mla_rows if normalize_party(r.party) == norm_party
#     ]

#     return PartyConstituenciesResponse(
#         party=norm_party,
#         constituencies=mp_constituencies + mla_constituencies
#     )
    
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
    ruling_party = PartyOut(id=1 if ruling_party_sn=="BJP" else 2,
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

        recent_performance.append(lokh_sabha_schemas.ElectionPerformanceOut(
            year=y,
            winner=lokh_sabha_schemas.PartyOut(id=1 if winner_sn=="BJP" else 2, short_name=winner_sn, full_name="Bharatiya Janata Party" if winner_sn=="BJP" else "Indian National Congress"),
            winner_seats=data[winner_sn],
            runner_up=lokh_sabha_schemas.PartyOut(id=1 if runner_sn=="BJP" else 2, short_name=runner_sn, full_name="Bharatiya Janata Party" if runner_sn=="BJP" else "Indian National Congress"),
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
        lokh_sabha_schemas.WinningProbabilityOut(party=lokh_sabha_schemas.PartyOut(id=2, short_name="INC", full_name="Indian National Congress"), probability_pct=prob_inc, projected_seats=int(prob_inc/100*total_seats), seat_change=0),
        lokh_sabha_schemas.WinningProbabilityOut(party=lokh_sabha_schemas.PartyOut(id=1, short_name="BJP", full_name="Bharatiya Janata Party"), probability_pct=prob_bjp, projected_seats=int(prob_bjp/100*total_seats), seat_change=0),
        lokh_sabha_schemas.WinningProbabilityOut(party=None, probability_pct=prob_oth, projected_seats=int(prob_oth/100*total_seats), seat_change=0)
    ]

    next_expected_wins = [
        lokh_sabha_schemas.NextExpectedWin(party=p.party if p.party else lokh_sabha_schemas.PartyOut(id=0, short_name="OTHERS", full_name="Others"),
                        wins_probability_pct=p.probability_pct,
                        projected_seats=p.projected_seats,
                        seat_change=p.seat_change)
        for p in probs
    ]

    predicted_winner = max(probs, key=lambda x: x.probability_pct).party
    predicted_confidence_pct = max(p.probability_pct for p in probs)

    return lokh_sabha_schemas.Section1Out(
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


# @router.get("/pc/party_info", response_model=Section1Out)
# def pc_party_info(state: str = Query("Rajasthan"), db: Session = Depends(get_db)):
    election_type = "PC"  # fixed for this endpoint

    # --- Latest year & total PCs in that year ---
    latest_year, total_seats = _latest_year_total_seats(db, state)

    # --- Yearly party seats (merged JNP->BJP) for the state ---
    yearly = _yearly_party_seats(db, state)
    if latest_year not in yearly or total_seats == 0:
        raise HTTPException(404, detail="No PCs/seats computed for latest year")

    # --- Current ruling (state-level LS leader = max seats in latest year) ---
    latest_map = yearly[latest_year]
    cur_sn, cur_seats, cur_runner_sn, cur_runner_seats = _winner_and_runner_up(latest_map)
    current_party = _party_out_from_sn(cur_sn)

    # --- Counts by winner across all LS cycles for this state ---
    merged_counts: Dict[str, int] = defaultdict(int)
    for y, seat_map in yearly.items():
        w_sn, w_seats, r_sn, r_seats = _winner_and_runner_up(seat_map)
        merged_counts[w_sn] += 1

    ruling_sn_merged = current_party.short_name
    ruling_track_count = int(merged_counts.get(ruling_sn_merged, 0))

    # --- Total governments (number of LS cycles recorded for this state) ---
    total_governments = int(len(yearly))

    # --- Opposition track record ---
    def party_obj(sn: str) -> PartyOut:
        po = _party_out_from_sn(sn)
        # If you have DB-backed Party table, you can hydrate ids/names here.
        return po

    opposition: List[OppositionTrackOut] = [
        OppositionTrackOut(party=party_obj(sn), governments=int(w))
        for sn, w in sorted(merged_counts.items(), key=lambda x: (-x[1], x[0]))
        if sn != ruling_sn_merged
    ]

    success_rate_pct = round((ruling_track_count / total_governments) * 100, 2) if total_governments else 0.0
    next_election_year = int(latest_year) + 5

    # --- Recent performance (year-wise winner & runner-up with seats) ---
    # Keep the same shape as your AC JSON. We’ll output for all available years ascending.
    recent_performance: List[YearPerformance] = []
    for y in sorted(yearly.keys()):
        seat_map = yearly[y]
        w_sn, w_seats, r_sn, r_seats = _winner_and_runner_up(seat_map)
        recent_performance.append(
            YearPerformance(
                year=int(y),
                winner=party_obj(w_sn),
                winner_seats=int(w_seats),
                runner_up=party_obj(r_sn),
                runner_up_seats=int(r_seats),
            )
        )

    # --- Dynamic probabilities (same logic as AC) ---
    bjp_wins = int(merged_counts.get("BJP", 0))
    inc_wins = int(merged_counts.get("INC", 0))
    others_wins = max(0, total_governments - (bjp_wins + inc_wins))

    if total_governments > 0:
        base_bjp = bjp_wins / total_governments
        base_inc = inc_wins / total_governments
    else:
        base_bjp = base_inc = 0.0
    base_oth = max(0.0, 1.0 - (base_bjp + base_inc))

    # anti-incumbency bonus: shift 10% from current to main opponent
    bonus = 0.10
    if ruling_sn_merged == "BJP":
        base_inc += bonus
    elif ruling_sn_merged == "INC":
        base_bjp += bonus

    # normalize
    s = base_bjp + base_inc + base_oth
    if s == 0:
        base_bjp, base_inc, base_oth = 0.48, 0.49, 0.03
    else:
        base_bjp, base_inc, base_oth = base_bjp/s, base_inc/s, base_oth/s

    # enforce Others floor & renormalize
    floor_oth = 0.03
    base_oth = max(base_oth, floor_oth)
    rem = 1.0 - base_oth
    denom = (base_bjp + base_inc) or 1.0
    base_bjp = rem * (base_bjp / denom)
    base_inc = rem * (base_inc / denom)

    prob_bjp = round(base_bjp * 100, 2)
    prob_inc = round(base_inc * 100, 2)
    prob_oth = round(100.0 - prob_bjp - prob_inc, 2)

    # --- Seats allocation from probabilities (exactly = total_seats) ---
    seat_alloc = _largest_remainder_allocation(
        [("INC", prob_inc), ("BJP", prob_bjp), ("OTHERS", prob_oth)],
        total_seats
    )
    inc_seats = int(seat_alloc.get("INC", 0))
    bjp_seats = int(seat_alloc.get("BJP", 0))
    oth_seats = int(seat_alloc.get("OTHERS", 0))

    # --- seat_change vs latest year seats ---
    last_inc = int(yearly[latest_year].get("INC", 0))
    last_bjp = int(yearly[latest_year].get("BJP", 0))
    last_oth = max(0, total_seats - (last_inc + last_bjp))

    inc_change = inc_seats - last_inc
    bjp_change = bjp_seats - last_bjp
    oth_change = oth_seats - last_oth

    # --- PartyOut objects for probability block ---
    inc = party_obj("INC")
    bjp = party_obj("BJP")
    oth = PartyOut(id=0, short_name="OTHERS", full_name="Others")

    # --- predicted winner & confidence ---
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

    # Rebuild opposition list (already computed above)
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