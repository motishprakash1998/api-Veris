# section1_router.py (models part only)
from __future__ import annotations

from typing import Optional, List
from decimal import Decimal

from sqlalchemy import (
    ForeignKey, UniqueConstraint,
    Integer, String, Text, Boolean, Numeric
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, declarative_base
from sqlalchemy.dialects.postgresql import ARRAY  # ✅ for TEXT[] arrays
from sqlalchemy import text  # for server_default on arrays if you want

Base = declarative_base()

# ---------------- ORM models ----------------
class AssemblyState(Base):
    __tablename__ = "assembly_states"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)

class AssemblyParty(Base):
    __tablename__ = "assembly_parties"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    short_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)   # e.g., BJP
    full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # ✅ Map Postgres TEXT[] properly
    aliases: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]")  # matches your table's DEFAULT '{}'
    )

class AssemblyElection(Base):
    __tablename__ = "assembly_elections"
    __table_args__ = (UniqueConstraint("state_id", "year", "election_type"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state_id: Mapped[int] = mapped_column(ForeignKey("assembly_states.id", ondelete="RESTRICT"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    election_type: Mapped[str] = mapped_column(String, nullable=False, default="AC")
    total_seats: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    state: Mapped["AssemblyState"] = relationship()

class AssemblyElectionPartyResult(Base):
    __tablename__ = "assembly_election_party_results"
    __table_args__ = (UniqueConstraint("election_id", "party_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    election_id: Mapped[int] = mapped_column(ForeignKey("assembly_elections.id", ondelete="CASCADE"), nullable=False)
    party_id: Mapped[int] = mapped_column(ForeignKey("assembly_parties.id", ondelete="RESTRICT"), nullable=False)
    seats_won: Mapped[int] = mapped_column(Integer, nullable=False)
    # Numeric -> Decimal is the most accurate mapping
    vote_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    is_winner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    election: Mapped["AssemblyElection"] = relationship()
    party: Mapped["AssemblyParty"] = relationship()

class AssemblyElectionSummary(Base):
    __tablename__ = "assembly_election_summary"
    election_id: Mapped[int] = mapped_column(
        ForeignKey("assembly_elections.id", ondelete="CASCADE"),
        primary_key=True
    )
    winning_party_id: Mapped[int] = mapped_column(ForeignKey("assembly_parties.id"), nullable=False)
    winning_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    winning_vote_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    top_vote_party_id: Mapped[int] = mapped_column(ForeignKey("assembly_parties.id"), nullable=False)
    top_vote_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    election: Mapped["AssemblyElection"] = relationship()
    winning_party: Mapped["AssemblyParty"] = relationship(foreign_keys=[winning_party_id])
    top_vote_party: Mapped["AssemblyParty"] = relationship(foreign_keys=[top_vote_party_id])
