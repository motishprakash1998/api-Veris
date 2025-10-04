from pydantic import BaseModel
from typing import List, Optional

class LokhPartyRepresentation(BaseModel):
    party: str
    seats: int
    percentage: float

class LokhConstituencyDetail(BaseModel):
    name: str
    type: str
    winning_candidate: str
    party: str
    margin: float

class LokhRepresentationBreakdown(BaseModel):
    current_mps: List[LokhPartyRepresentation]
    current_mlas: List[LokhPartyRepresentation]
    predicted_mps: List[LokhPartyRepresentation]
    predicted_mlas: List[LokhPartyRepresentation]

class LokhPartyConstituenciesResponse(BaseModel):
    party: str
    constituencies: List[LokhConstituencyDetail]

# from pydantic import BaseModel
# from typing import List, Optional

class LokhPartyOut(BaseModel):
    id: int
    short_name: str
    full_name: str

class LokhOppositionTrackOut(BaseModel):
    party: LokhPartyOut
    governments: int

class LokhElectionPerformanceOut(BaseModel):
    year: int
    winner: LokhPartyOut
    winner_seats: int
    runner_up: LokhPartyOut
    runner_up_seats: int

class LokhWinningProbabilityOut(BaseModel):
    party: Optional[LokhPartyOut]
    probability_pct: float
    projected_seats: int
    seat_change: int

class LokhNextExpectedWin(BaseModel):
    party: LokhPartyOut
    wins_probability_pct: float
    projected_seats: int
    seat_change: int

class LokhSection1Out(BaseModel):
    state: str
    election_type: str
    current_ruling_party: LokhPartyOut
    current_ruling_year: int
    ruling_party_track_record_count: int
    total_governments: int
    opposition_track_record: List[LokhOppositionTrackOut]
    total_terms_current_ruling: int
    success_rate_pct: float
    next_election_year: int
    recent_performance: List[LokhElectionPerformanceOut]
    predicted_winner: LokhPartyOut
    predicted_confidence_pct: float
    winning_probabilities: List[LokhWinningProbabilityOut]
    next_expected_wins: List[LokhNextExpectedWin]

class YearPerformance(BaseModel):
    year: int
    winner: "LokhPartyOut" 
    winner_seats: int
    runner_up: "LokhPartyOut"
    runner_up_seats: int