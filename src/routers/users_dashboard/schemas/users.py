from pydantic import BaseModel
from typing import List, Optional

# -------------- Pydantic outputs --------------
class PartyOut(BaseModel):
    id: int
    short_name: str
    full_name: Optional[str] = None

class OppositionTrackOut(BaseModel):
    party: PartyOut
    governments: int

class WinningProbabilityOut(BaseModel):
    party: Optional[PartyOut]
    probability_pct: float
    projected_seats: Optional[int] = None
    seat_change: Optional[int] = None  # vs last win/last election, if you compute

# NEW: year-wise winner/runner-up for the bar chart
class RecentPerformanceItem(BaseModel):
    year: int
    winner: PartyOut
    winner_seats: int
    runner_up: Optional[PartyOut] = None
    runner_up_seats: Optional[int] = None

# NEW: compact card for “Next expected wins”
class NextExpectedWin(BaseModel):
    party: PartyOut
    wins_probability_pct: float
    projected_seats: Optional[int] = None
    seat_change: Optional[int] = None

class Section1Out(BaseModel):
    state: str
    election_type: str

    current_ruling_party: PartyOut
    current_ruling_year: int

    # existing
    ruling_party_track_record_count: int
    total_governments: int
    opposition_track_record: List[OppositionTrackOut]

    # NEW for your UI
    total_terms_current_ruling: int     # same as track record (after JNP→BJP merge)
    success_rate_pct: float             # wins / total_governments * 100 (merged)
    next_election_year: int             # current_ruling_year + 5

    recent_performance: List[RecentPerformanceItem]  # last 5 elections

    predicted_winner: Optional[PartyOut] = None
    predicted_confidence_pct: Optional[float] = None

    # detailed bars
    winning_probabilities: List[WinningProbabilityOut]  # keep
    next_expected_wins: List[NextExpectedWin]           # Congress / BJP / Others cards