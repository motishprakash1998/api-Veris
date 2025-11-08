from sqlalchemy import Column, Integer, String, BigInteger, Numeric, Text, UniqueConstraint, JSON,Enum,Boolean,DateTime
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class AssemblyAffidavit(Base):
    __tablename__ = "candidate_affidavits_ac"  

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
    ac_name = Column(String(255), nullable=True)
    state_name = Column(String(255), nullable=True)
    assembly_type = Column(String(50), nullable=True)
    
    # Candidate history column
    candidate_history = Column(JSON, nullable=True) 
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
            name="affidavit_verification_status_enum",  # 👈 different enum name for this table
        ),
        nullable=False,
        default="under_review",
    )
    
    # Optional: prevent duplicate entries for the same candidate, year, and PC
    __table_args__ = (
        UniqueConstraint("candidate_name", "year", "ac_name", name="uix_candidate_year_pc"),
    )
