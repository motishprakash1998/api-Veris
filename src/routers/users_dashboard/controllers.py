from typing import Dict, Optional,Set
from .schemas.users import (PartyOut,RecentPerformanceItem)
import numpy as np

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
from sqlalchemy.orm import Session
from src.routers.users_dashboard.models.users import (
    AssemblyState as ST, AssemblyParty as PT,
    AssemblyElection as EL, AssemblyElectionPartyResult as EPR,
    AssemblyElectionSummary as SUM
)
from loguru import logger
from decimal import Decimal
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

from typing import Any, Dict, List
import decimal
from sqlalchemy import text
from sqlalchemy.orm import Session
import  re

def _to_json_value(v: Any):
    """
    Helper: return numeric (int/float) or boolean as-is,
    convert Decimal -> float, and None -> 'NA', else return as-is (str).
    """
    if v is None:
        return "NA"
    if isinstance(v, decimal.Decimal):
        # convert Decimal to float for JSON friendliness
        try:
            return float(v)
        except Exception:
            return str(v)
    if isinstance(v, (int, float, bool)):
        return v
    return v  # string or other types

def get_parliament_dashboard_data(db: Session, candidate_name: str) -> Dict:
    """
    Query public.parliament_candidate_information (via SQLAlchemy Session)
    and return the requested 'parliament' structure.

    Args:
      db: sqlalchemy.orm.Session
      candidate_name: exact candidate name to filter by

    Returns:
      dict with 'parliament' key (see docstring examples above)
    """
    sql = """
    SELECT
      pc_name,
      "year",
      party,
      votes,
      vote_percent,
      "position",
      margin_votes,
      margin_percent,
      total_votes_polled_num,
      booths,
      electors,
      female_electors,
      male_electors,
      nota_votes
    FROM public.parliament_candidate_information
    WHERE candidate = :candidate_name
    ORDER BY "year" DESC NULLS LAST, votes DESC NULLS LAST;
    """

    result_rows = []
    try:
        stmt = text(sql)
        result = db.execute(stmt, {"candidate_name": candidate_name})
        # .mappings() returns RowMapping objects that behave like dicts
        result_rows = result.mappings().all()
    except Exception as e:
        # Optionally log or re-raise; return NA structure to avoid 500 if preferred.
        # Here we'll re-raise so caller can see the error (adjust if you prefer silent NA).
        raise

    # if no rows, return one NA-filled election_history object
    if not result_rows:
        na_entry = {
            "year": "NA",
            "election_type": "Parliament",
            "constituency": "NA",
            "party": "NA",
            "votes_obtained": "NA",
            "vote_share_pct": "NA",
            "position": "NA",
            "margin": "NA",
            "total_votes": "NA",
            "result": "NA",
            "source": "NA",
        }
        return {
            "parliament": {
                "constituency": "NA",
                "election_history": [na_entry],
                "committee_memberships": [],
                "parliamentary_performance": {
                    "questions_asked": "NA",
                    "bills_introduced": "NA",
                    "attendance_pct": "NA",
                    "debates_participated": "NA",
                },
            }
        }

    election_history: List[Dict] = []
    constituency = None

    for row in result_rows:
        # row behaves like a dict (RowMapping)
        if constituency is None and row.get("pc_name") is not None:
            constituency = row.get("pc_name")

        year = _to_json_value(row.get("year"))
        party = _to_json_value(row.get("party"))
        votes_obtained = _to_json_value(row.get("votes"))
        vote_share_pct = _to_json_value(row.get("vote_percent"))
        position = _to_json_value(row.get("position"))

        # margin: prefer margin_votes, else margin_percent
        mv = row.get("margin_votes")
        mp = row.get("margin_percent")
        if mv is not None:
            margin_val = _to_json_value(mv)
        elif mp is not None:
            margin_val = _to_json_value(mp)
        else:
            margin_val = "NA"

        total_votes = _to_json_value(row.get("total_votes_polled_num"))

        # determine result
        if row.get("position") is None:
            result_str = "NA"
        else:
            try:
                pos_int = int(row.get("position"))
                result_str = "won" if pos_int == 1 else "lost"
            except Exception:
                result_str = "NA"

        entry = {
            "year": year,
            "election_type": "Parliament",
            "constituency": _to_json_value(row.get("pc_name")),
            "party": party,
            "votes_obtained": votes_obtained,
            "vote_share_pct": vote_share_pct,
            "position": position,
            "margin": margin_val,
            "total_votes": total_votes,
            "result": result_str,
            "source": "NA",
        }
        election_history.append(entry)

    if constituency is None:
        constituency = "NA"

    return {
        "parliament": {
            "constituency": constituency,
            "election_history": election_history,
            "committee_memberships": [],
            "parliamentary_performance": {
                "questions_asked": "NA",
                "bills_introduced": "NA",
                "attendance_pct": "NA",
                "debates_participated": "NA",
            },
        }
    }

def get_assembly_dashboard_data(db: Session, candidate_name: str) -> Dict:
    """
    Query the public.assembly_candidate_information table for candidate_name
    and return a dict with the 'assembly' structure requested.

    Args:
      db: SQLAlchemy Session
      candidate_name: candidate name to filter by (exact match)

    Returns:
      dict: {
        "assembly": {
          "constituency": <ac_name or 'NA'>,
          "election_history": [ ... ],
          "committee_memberships": [],
          "assembly_performance": {
             "questions_asked": "NA",
             "bills_introduced": "NA",
             "attendance_pct": "NA",
             "debates_participated": "NA"
          }
        }
      }
    """

    sql = """
    SELECT
      ac_name,
      "year",
      party,
      votes,
      vote_percent,
      "position",
      margin_votes,
      margin_percent,
      total_votes_polled_num,
      booths,
      electors,
      female_electors,
      male_electors,
      female_voters,
      male_voters,
      nota_votes
    FROM public.assembly_candidate_information
    WHERE candidate = :candidate_name
    ORDER BY "year" DESC NULLS LAST, votes DESC NULLS LAST;
    """

    try:
        stmt = text(sql)
        result = db.execute(stmt, {"candidate_name": candidate_name})
        rows = result.mappings().all()
    except Exception as e:
        raise

    # If no records found
    if not rows:
        na_entry = {
            "year": "NA",
            "election_type": "Assembly",
            "constituency": "NA",
            "party": "NA",
            "votes_obtained": "NA",
            "vote_share_pct": "NA",
            "position": "NA",
            "margin": "NA",
            "total_votes": "NA",
            "result": "NA",
            "source": "NA",
        }
        return {
            "assembly": {
                "constituency": "NA",
                "election_history": [na_entry],
                "committee_memberships": [],
                "assembly_performance": {
                    "questions_asked": "NA",
                    "bills_introduced": "NA",
                    "attendance_pct": "NA",
                    "debates_participated": "NA",
                },
            }
        }

    election_history: List[Dict] = []
    constituency = None

    for row in rows:
        if constituency is None and row.get("ac_name") is not None:
            constituency = row.get("ac_name")

        year = _to_json_value(row.get("year"))
        party = _to_json_value(row.get("party"))
        votes_obtained = _to_json_value(row.get("votes"))
        vote_share_pct = _to_json_value(row.get("vote_percent"))
        position = _to_json_value(row.get("position"))

        # margin
        mv = row.get("margin_votes")
        mp = row.get("margin_percent")
        if mv is not None:
            margin_val = _to_json_value(mv)
        elif mp is not None:
            margin_val = _to_json_value(mp)
        else:
            margin_val = "NA"

        total_votes = _to_json_value(row.get("total_votes_polled_num"))

        # determine result
        if row.get("position") is None:
            result_str = "NA"
        else:
            try:
                pos_int = int(row.get("position"))
                result_str = "won" if pos_int == 1 else "lost"
            except Exception:
                result_str = "NA"

        entry = {
            "year": year,
            "election_type": "Assembly",
            "constituency": _to_json_value(row.get("ac_name")),
            "party": party,
            "votes_obtained": votes_obtained,
            "vote_share_pct": vote_share_pct,
            "position": position,
            "margin": margin_val,
            "total_votes": total_votes,
            "result": result_str,
            "source": "NA",
        }
        election_history.append(entry)

    if constituency is None:
        constituency = "NA"

    return {
        "assembly": {
            "constituency": constituency,
            "election_history": election_history,
            "committee_memberships": [],
            "assembly_performance": {
                "questions_asked": "NA",
                "bills_introduced": "NA",
                "attendance_pct": "NA",
                "debates_participated": "NA",
            },
        }
    }
    
  
# Simple heuristic lists for gender inference
_MALE_NAMES = {"rajesh", "ravi", "amit", "suresh", "lalchand", "ashok", "rahul", "vikas", "anil", "sunil", "ajay"}
_FEMALE_NAMES = {"anita", "poonam", "suman", "neha", "priya", "kavita", "rekha", "jyoti", "geeta", "meenakshi", "savita"}

def _infer_gender(display_name: str) -> str:
    if not display_name:
        return "Unknown"
    name = display_name.lower()
    tokens = re.sub(r"[^\w]+", " ", name).split()
    if not tokens:
        return "Unknown"
    first = tokens[0]
    if first in _MALE_NAMES:
        return "Male"
    if first in _FEMALE_NAMES:
        return "Female"
    # fallback heuristic
    if first.endswith("a") or first.endswith("i"):
        return "Female"
    return "Unknown"


# Optional helper (simplify or expand as you wish)
party_mapping = {
    "Bharatiya Janata Party": "BJP",
    "Indian National Congress": "INC",
    "Bahujan Samaj Party": "BSP",
    "Aam Aadmi Party": "AAP",
    "Communist Party of India": "CPI",
    "Communist Party of India (Marxist)": "CPI(M)",
}

def get_basic_info_leader(
    db: Session,
    limit: int = 1,
    candidate_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Fetch leader's profile info and enrich with party + latest political position.
    """
    base_sql = """
        SELECT
            social_account_id,
            display_name,
            bio,
            profile_image_url
        FROM public.account_profiles
    """

    if candidate_name:
        base_sql += " WHERE LOWER(display_name) LIKE LOWER(:candidate_name)"
    base_sql += " ORDER BY retrieved_at DESC LIMIT :limit"

    params = {"limit": limit}
    if candidate_name:
        params["candidate_name"] = f"%{candidate_name}%"

    try:
        rows = db.execute(text(base_sql), params).mappings().all()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        print(f"DB Error fetching account_profiles: {e}")
        return []

    results = []
    for r in rows:
        display_name = r.get("display_name")

        # --- Step 1: Fetch last known election record ---
        candidate_filter = {"candidate_name": f"%{display_name}%"}
        assembly_sql = """
            SELECT ac_name AS constituency, party, year
            FROM public.assembly_candidate_information
            WHERE LOWER(candidate) LIKE LOWER(:candidate_name)
            ORDER BY year DESC
            LIMIT 1
        """
        parliament_sql = """
            SELECT pc_name AS constituency, party, year
            FROM public.parliament_candidate_information
            WHERE LOWER(candidate) LIKE LOWER(:candidate_name)
            ORDER BY year DESC
            LIMIT 1
        """

        assembly_row = db.execute(text(assembly_sql), candidate_filter).mappings().first()
        parliament_row = db.execute(text(parliament_sql), candidate_filter).mappings().first()

        # Determine which record is latest
        latest_record = None
        if assembly_row and parliament_row:
            latest_record = assembly_row if assembly_row["year"] > parliament_row["year"] else parliament_row
        else:
            latest_record = assembly_row or parliament_row

        # --- Step 2: Build dynamic data ---
        party_info = {
            "id": None,
            "short_name": None,
            "full_name": None
        }
        current_positions = []

        if latest_record:
            party_name = latest_record.get("party")
            short_name = party_mapping.get(party_name, None)
            party_info = {
                "id": None,
                "short_name": short_name,
                "full_name": party_name
            }

            position_type = "MLA" if "ac_name" in latest_record.keys() or "constituency" in latest_record else "MP"
            body = "State Assembly" if position_type == "MLA" else "Lok Sabha"

            current_positions = [{
                "type": position_type,
                "body": body,
                "constituency": latest_record.get("constituency"),
                "from": f"{latest_record.get('year')}",
                "to": None
            }]
        # Build public URL using Source bucket name  env var (fallback to requestable domain if not present)
        import os
        import urllib.parse
        import logging
        from src.routers.employees import controller
        profile_path = r.get("profile_image_url", "").lstrip("/")
        source_bucket_name = os.environ.get("SOURCE_BUCKET_NAME")
        if not source_bucket_name:
            logging.warning("DOMAIN env var not set; returning path without domain")
            public_url = profile_path
        else:
            # ensure path is URL-encoded
            encoded_path = urllib.parse.quote(profile_path)
            public_url = controller.generate_presigned_url(source_bucket_name, profile_path)
        # --- Step 3: Combine full response ---
        results.append({
            "id": r.get("social_account_id"),
            "name": display_name or None,
            "aliases": [],
            "bio": r.get("bio") or None,
            "dob": "NA",
            "gender": _infer_gender(display_name),
            "photo_url": public_url or None,
            "party": party_info,
            "current_positions": current_positions,
            "profile": {
                "summary": None,
                "education": [],
                "profession": None,
                "contact": {
                    "email": None,
                    "phone": None,
                    "office_address": None
                }
            }
        })

    return results

def to_float(val):
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(val)
    except:
        return 0.0

def social_media_info(db: Session, display_name: str) -> Dict[str, Any]:
    """
    Fetch social media performance info for a given leader by display name.
    Returns platform-level and combined metrics including total likes/comments.
    """

    sql_accounts = """
        SELECT
            sa.id AS social_account_id,
            sa.username,
            sa.profile_url,
            p.code AS platform_code,
            p.display_name AS platform_name,
            ap.follower_count,
            ap.like_count,
            ap.following_count,
            ap.post_count,
            ap.retrieved_at
        FROM public.account_profiles ap
        JOIN public.social_accounts sa ON ap.social_account_id = sa.id
        JOIN public.platforms p ON sa.platform_id = p.id
        WHERE LOWER(ap.display_name) LIKE LOWER(:display_name)
        ORDER BY ap.retrieved_at DESC
    """

    try:
        accounts = db.execute(
            text(sql_accounts),
            {"display_name": f"%{display_name}%"}
        ).mappings().all()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        print(f"DB Error fetching account_profiles for {display_name}: {e}")
        return {
            "social_media": {
                "platforms": {},
                "combined_followers": None,
                "combined_engagement_pct": None
            }
        }

    platforms_data = {}
    total_followers = 0
    engagement_rates = []

    for acc in accounts:
        platform_code = acc.get("platform_code")
        followers = to_float(acc.get("follower_count"))
        last_updated = acc.get("retrieved_at")
        total_likes = None
        total_comments = None
        engagement_rate = None

        # --- Facebook ---
        if platform_code == "facebook":
            total_likes = to_float(acc.get("like_count"))
            engagement_rate = round((total_likes / followers) * 100, 2) if followers else 0.0

        # --- Instagram ---
        elif platform_code == "instagram":
            post_sql = """
                SELECT
                    COALESCE(SUM(likes), 0) AS total_likes,
                    COALESCE(SUM("comment"), 0) AS total_comments,
                    COUNT(*) AS post_count
                FROM public.instagram_posts
                WHERE social_account_id = :social_account_id
            """
            post_stats = db.execute(
                text(post_sql),
                {"social_account_id": acc["social_account_id"]}
            ).mappings().first()

            total_likes = to_float(post_stats.get("total_likes"))
            total_comments = to_float(post_stats.get("total_comments"))
            post_count = to_float(post_stats.get("post_count"))

            if post_count > 0 and followers > 0:
                avg_engagement = (total_likes + total_comments) / post_count
                engagement_rate = round((avg_engagement / followers) * 100, 2)
            else:
                engagement_rate = 0.0

        # Save platform info
        platform_entry = {
            "followers": followers,
            "engagement_rate": engagement_rate,
            "last_updated": last_updated.isoformat() if last_updated else None
        }

        if platform_code == "facebook":
            platform_entry.update({
                "page": acc.get("username"),
                "total_likes": total_likes
            })
        elif platform_code == "instagram":
            platform_entry.update({
                "handle": acc.get("username"),
                "total_likes": total_likes,
                "total_comments": total_comments
            })

        platforms_data[platform_code] = platform_entry
        total_followers += followers
        engagement_rates.append(engagement_rate)

    combined_engagement = (
        round(sum(engagement_rates) / len(engagement_rates), 2)
        if engagement_rates else None
    )

    result = {
        "social_media": {
            "platforms": {
                "facebook": platforms_data.get("facebook", {
                    "page": None,
                    "followers": None,
                    "total_likes": None,
                    "engagement_rate": None,
                    "last_updated": None
                }),
                "instagram": platforms_data.get("instagram", {
                    "handle": None,
                    "followers": None,
                    "total_likes": None,
                    "total_comments": None,
                    "engagement_rate": None,
                    "last_updated": None
                }),
            },
            "combined_followers": total_followers if total_followers > 0 else None,
            "combined_engagement_pct": combined_engagement
        }
    }

    return result