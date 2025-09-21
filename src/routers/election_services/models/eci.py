# app/models.py

from sqlalchemy import Column, Integer, String, Float, BigInteger, ForeignKey,Boolean, DateTime,Enum
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


# -------------------------
#  State Table
# -------------------------
class State(Base):
    __tablename__ = "states"

    state_id = Column(Integer, primary_key=True, autoincrement=True)
    state_name = Column(String, unique=True, nullable=False)

    # Relationships
    constituencies = relationship("Constituency", back_populates="state")


# -------------------------
#  Constituency Table
# -------------------------
class Constituency(Base):
    __tablename__ = "parliamentary_constituencies"

    pc_id = Column(Integer, primary_key=True, autoincrement=True)
    pc_name = Column(String, nullable=False)
    state_id = Column(Integer, ForeignKey("states.state_id"))
    total_electors = Column(BigInteger)

    # Relationships
    state = relationship("State", back_populates="constituencies")
    elections = relationship("Election", back_populates="constituency")


# -------------------------
#  Party Table
# -------------------------
class Party(Base):
    __tablename__ = "parties"

    party_id = Column(Integer, primary_key=True, autoincrement=True)
    party_name = Column(String, nullable=False)
    party_symbol = Column(String)

    # Relationships
    candidates = relationship("Candidate", back_populates="party")


# -------------------------
#  Candidate Table
# -------------------------
class Candidate(Base):
    __tablename__ = "candidates"

    candidate_id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_name = Column(String)
    gender = Column(String)
    age = Column(Float)
    category = Column(String)
    party_id = Column(Integer, ForeignKey("parties.party_id"))

    # Relationships
    party = relationship("Party", back_populates="candidates")
    results = relationship("Result", back_populates="candidate")


# -------------------------
#  Election Table
# -------------------------
class Election(Base):
    __tablename__ = "elections"

    election_id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False)
    pc_id = Column(Integer, ForeignKey("parliamentary_constituencies.pc_id"))
    total_votes_polled_in_constituency = Column(BigInteger)
    valid_votes = Column(BigInteger)

    # Relationships
    constituency = relationship("Constituency", back_populates="elections")
    results = relationship("Result", back_populates="election")


# -------------------------
#  Result Table
# -------------------------
class Result(Base):
    __tablename__ = "results"

    result_id = Column(Integer, primary_key=True, autoincrement=True)
    election_id = Column(Integer, ForeignKey("elections.election_id"))
    candidate_id = Column(Integer, ForeignKey("candidates.candidate_id"))
    general_votes = Column(BigInteger)
    postal_votes = Column(BigInteger)
    total_votes = Column(BigInteger)
    over_total_electors_in_constituency = Column(Float)
    over_total_votes_polled_in_constituency = Column(Float)
    over_total_valid_votes_polled_in_constituency = Column(Float)

    # Relationships
    election = relationship("Election", back_populates="results")
    candidate = relationship("Candidate", back_populates="results")
    
     # Soft-delete fields
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime, nullable=True)
    
    # ✅ Verification status with rejection handling
    verification_status = Column(
        Enum(
            "under_review",
            "verified_employee",
            "verified_admin",
            "rejected_admin",
            name="verification_status_enum"
        ),
        nullable=False,
        default="under_review"
    )


# -------------------------
#  Create all tables
# -------------------------
# Base.metadata.create_all(bind=engine)
