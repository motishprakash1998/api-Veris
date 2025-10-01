from typing import Dict, Optional
from .schemas.users import (PartyOut,RecentPerformanceItem)

def _party_out(row) -> PartyOut:
    return PartyOut(id=row.id, short_name=row.short_name, full_name=row.full_name)

def _predict_next(current_party_id: int, counts_by_party: Dict[int, int]) -> Optional[int]:
    # Pick the non-current party with the most historical wins
    return max(
        (pid for pid in counts_by_party.keys() if pid != current_party_id),
        key=lambda pid: counts_by_party[pid],
        default=None
    )
    
from typing import Dict, Tuple, List
from sqlalchemy import select, func, desc
from sqlalchemy.sql import over
from src.routers.users_dashboard.models.users import (
    AssemblyState as ST, AssemblyParty as PT,
    AssemblyElection as EL, AssemblyElectionPartyResult as EPR,
    AssemblyElectionSummary as SUM
)

# merge JNP → BJP at “code” level using short_name
def _merge_code(short_name: str) -> str:
    return "BJP" if short_name in ("BJP", "JNP") else short_name

def _merge_counts_by_short_name(rows: List[Tuple[int, str, str, int]]) -> Dict[str, int]:
    # rows: (party_id, short_name, full_name, wins)
    merged: Dict[str, int] = {}
    for _pid, sn, _fn, wins in rows:
        key = _merge_code(sn)
        merged[key] = merged.get(key, 0) + int(wins)
    return merged

def _recent_performance(db, state: str, etype: str, limit_years: int = 5):
    # top-2 parties by seats per election for last N elections
    # SQLAlchemy window row_number()
    rn = func.row_number().over(
        partition_by=EPR.election_id,
        order_by=(EPR.seats_won.desc(), EPR.vote_percent.desc(), EPR.party_id.asc())
    )
    q = (
        select(
            EL.year,
            PT.id, PT.short_name, PT.full_name,
            EPR.seats_won,
            rn.label("rn"),
        )
        .join(EL, EL.id == EPR.election_id)
        .join(ST, ST.id == EL.state_id)
        .join(PT, PT.id == EPR.party_id)
        .where(ST.name == state, EL.election_type == etype)
        .order_by(EL.year.desc(), EPR.seats_won.desc())
    )
    rows = db.execute(q).all()

    # collect top-2 per year
    per_year = {}
    for year, pid, sn, fn, seats, rrn in rows:
        item = {"party": PartyOut(id=pid, short_name=sn, full_name=fn), "seats": int(seats)}
        y = int(year)
        if rrn == 1:
            per_year[y] = {"winner": item}
        elif rrn == 2:
            per_year.setdefault(y, {})
            per_year[y]["runner_up"] = item

    years = sorted(per_year.keys(), reverse=True)[:limit_years]
    result = []
    for y in years:
        w = per_year[y].get("winner")
        r = per_year[y].get("runner_up")
        if not w:
            continue
        result.append(
            RecentPerformanceItem(
                year=y,
                winner=w["party"], winner_seats=w["seats"],
                runner_up=r["party"] if r else None,
                runner_up_seats=r["seats"] if r else None,
            )
        )
    # return in ascending order for charts
    return sorted(result, key=lambda x: x.year)

def _allocate_seats_from_probs(prob_map, total_seats=200):
    """
    prob_map: list of tuples (key, prob_pct) where key is 'INC'/'BJP'/'OTHERS'
    Returns dict: {key: seats}
    Uses largest-remainder method so sum == total_seats.
    """
    # 1) raw quotas
    quotas = {k: (p/100.0) * total_seats for k, p in prob_map}
    # 2) floors + track remainders
    floors = {k: int(quotas[k] // 1) for k in quotas}
    remainders = {k: quotas[k] - floors[k] for k in quotas}
    used = sum(floors.values())
    left = total_seats - used
    # 3) assign remaining seats to largest remainders
    order = sorted(remainders.items(), key=lambda x: x[1], reverse=True)
    for i in range(left):
        floors[order[i][0]] += 1
    return floors
