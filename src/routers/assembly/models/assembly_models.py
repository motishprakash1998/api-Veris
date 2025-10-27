from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Numeric,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class ElectionMaster(Base):
    __tablename__ = "election_master"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    year = Column(Integer, nullable=False)
    election_type = Column(String(50), nullable=False)
    state = Column(String(100), nullable=True)

    is_deleted = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at = Column(DateTime(timezone=False), nullable=True)

    # relationships
    results = relationship(
        "ConstituencyResults", back_populates="election", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<ElectionMaster(id={self.id}, year={self.year}, type={self.election_type})>"


class ConstituencyMaster(Base):
    __tablename__ = "constituency_master"
    __table_args__ = (UniqueConstraint("ac_no", "state", name="uq_ac_no_state"),)

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    ac_no = Column(Integer, nullable=False)
    ac_name = Column(String(150), nullable=False)
    district = Column(String(100), nullable=True)
    ac_type = Column(String(10), nullable=True)
    state = Column(String(100), nullable=True)

    is_deleted = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at = Column(DateTime(timezone=False), nullable=True)

    # relationships
    results = relationship(
        "ConstituencyResults", back_populates="constituency", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<ConstituencyMaster(ac_no={self.ac_no}, ac_name={self.ac_name})>"


class ConstituencyResults(Base):
    __tablename__ = "constituency_results"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )

    election_id = Column(
        UUID(as_uuid=True),
        ForeignKey("election_master.id", ondelete="CASCADE"),
        nullable=False,
    )
    constituency_id = Column(
        UUID(as_uuid=True),
        ForeignKey("constituency_master.id", ondelete="CASCADE"),
        nullable=False,
    )

    total_electors = Column(Integer, nullable=True)
    male_electors = Column(Integer, nullable=True)
    female_electors = Column(Integer, nullable=True)
    total_votes = Column(Integer, nullable=True)
    poll_percent = Column(Numeric(5, 2), nullable=True)
    nota_votes = Column(Integer, nullable=True)
    nota_percent = Column(Numeric(5, 2), nullable=True)

    winning_candidate = Column(String(150), nullable=True)
    winning_party = Column(String(150), nullable=True)
    margin = Column(Integer, nullable=True)
    margin_percent = Column(Numeric(5, 2), nullable=True)

    is_deleted = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at = Column(DateTime(timezone=False), nullable=True)

    # relationships
    election = relationship("ElectionMaster", back_populates="results")
    constituency = relationship("ConstituencyMaster", back_populates="results")
    candidates = relationship(
        "ConstituencyCandidates", back_populates="result", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<ConstituencyResults(id={self.id}, election_id={self.election_id}, "
            f"constituency_id={self.constituency_id})>"
        )


class ConstituencyCandidates(Base):
    __tablename__ = "constituency_candidates"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    result_id = Column(
        UUID(as_uuid=True),
        ForeignKey("constituency_results.id", ondelete="CASCADE"),
        nullable=False,
    )

    position = Column(Integer, nullable=True)
    candidate = Column(String(150), nullable=True)  # renamed from "name" in your DDL
    party = Column(String(150), nullable=True)
    votes = Column(Integer, nullable=True)
    vote_percent = Column(Numeric(5, 2), nullable=True)

    is_deleted = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at = Column(DateTime(timezone=False), nullable=True)

    # relationships
    result = relationship("ConstituencyResults", back_populates="candidates")

    def __repr__(self):
        return f"<ConstituencyCandidates(candidate={self.candidate}, party={self.party})>"
