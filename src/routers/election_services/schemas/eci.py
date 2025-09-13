# schemas/election_services.py
from pydantic import BaseModel
from typing import List

# src/schemas/election_services.py
from pydantic import BaseModel
from typing import List

class ElectionServiceItem(BaseModel):
    state_name: str | None
    pc_name: str | None
    candidate_name: str | None
    sex: str | None
    age: float | None
    category: str | None
    party_name: str | None
    party_symbol: str | None
    general_votes: int | None
    postal_votes: int | None
    total_votes: int | None
    over_total_electors_in_constituency: float | None
    over_total_votes_polled_in_constituency: float | None
    total_electors: int | None
    year: int | None

    # if you ever pass ORM objects instead of dicts, enable:
    model_config = {"from_attributes": True}


class ElectionServicesResponse(BaseModel):
    total: int
    items: List[ElectionServiceItem]
