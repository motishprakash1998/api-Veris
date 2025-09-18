from sqlalchemy import Column, Integer, String, BigInteger, Numeric, Text, UniqueConstraint, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Affidavit(Base):
    __tablename__ = "candidate_affidavits"   # 👈 renamed table

    affidavit_id = Column(Integer, primary_key=True, autoincrement=True)

    # Direct columns (flat table, no relations)
    candidate_name = Column(String(255), nullable=False)
    party_name = Column(String(255), nullable=True)
    criminal_cases = Column(Integer, default=0)
    education = Column(String(255), nullable=True)
    age = Column(Numeric, nullable=True)  # 👈 Numeric instead of Float for PostgreSQL
    total_assets = Column(BigInteger, nullable=True)
    liabilities = Column(BigInteger, nullable=True)
    candidate_link = Column(Text, nullable=True)  # 👈 use Text for long URLs
    year = Column(Integer, nullable=False)
    pc_name = Column(String(255), nullable=True)
    state_name = Column(String(255), nullable=True)
    
    # Candidate history column
    candidate_history = Column(JSON, nullable=True) 
    
    # Optional: prevent duplicate entries for the same candidate, year, and PC
    __table_args__ = (
        UniqueConstraint("candidate_name", "year", "pc_name", name="uix_candidate_year_pc"),
    )
