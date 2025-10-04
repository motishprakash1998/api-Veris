from pydantic import BaseModel
from typing import List, Optional

class PartyRepresentation(BaseModel):
    party: str
    seats: int
    percentage: float

class ConstituencyDetail(BaseModel):
    name: str
    type: str
    winning_candidate: str
    party: str
    margin: float

class RepresentationBreakdown(BaseModel):
    current_mps: List[PartyRepresentation]
    current_mlas: List[PartyRepresentation]
    predicted_mps: List[PartyRepresentation]
    predicted_mlas: List[PartyRepresentation]

class PartyConstituenciesResponse(BaseModel):
    party: str
    constituencies: List[ConstituencyDetail]

# from pydantic import BaseModel
# from typing import List, Optional

class PartyOut(BaseModel):
    id: int
    short_name: str
    full_name: str

class OppositionTrackOut(BaseModel):
    party: PartyOut
    governments: int

class ElectionPerformanceOut(BaseModel):
    year: int
    winner: PartyOut
    winner_seats: int
    runner_up: PartyOut
    runner_up_seats: int

class WinningProbabilityOut(BaseModel):
    party: Optional[PartyOut]
    probability_pct: float
    projected_seats: int
    seat_change: int

class NextExpectedWin(BaseModel):
    party: PartyOut
    wins_probability_pct: float
    projected_seats: int
    seat_change: int

class Section1Out(BaseModel):
    state: str
    election_type: str
    current_ruling_party: PartyOut
    current_ruling_year: int
    ruling_party_track_record_count: int
    total_governments: int
    opposition_track_record: List[OppositionTrackOut]
    total_terms_current_ruling: int
    success_rate_pct: float
    next_election_year: int
    recent_performance: List[ElectionPerformanceOut]
    predicted_winner: PartyOut
    predicted_confidence_pct: float
    winning_probabilities: List[WinningProbabilityOut]
    next_expected_wins: List[NextExpectedWin]



class PartyOut(BaseModel):
    id: int
    short_name: str
    full_name: str

class OppositionTrackOut(BaseModel):
    party: PartyOut
    governments: int

class ElectionPerformanceOut(BaseModel):
    year: int
    winner: PartyOut
    winner_seats: int
    runner_up: PartyOut
    runner_up_seats: int

class WinningProbabilityOut(BaseModel):
    party: Optional[PartyOut]
    probability_pct: float
    projected_seats: int
    seat_change: int

class NextExpectedWin(BaseModel):
    party: PartyOut
    wins_probability_pct: float
    projected_seats: int
    seat_change: int

class YearPerformance(BaseModel):
    year: int
    winner: "PartyOut"        # assumes PartyOut is defined elsewhere
    winner_seats: int
    runner_up: "PartyOut"
    runner_up_seats: int