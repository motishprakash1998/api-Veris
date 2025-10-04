from sqlalchemy import Column, Integer, String, BigInteger, Numeric
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class VidhanSabhaResult(Base):
    __tablename__ = "vidhan_sabha_results"
    id = Column(Integer, primary_key=True, index=True)
    ac_name = Column(String(255))
    ac_no = Column(Integer)
    ac_type = Column(String(50))
    district = Column(String(100))
    winning_candidate = Column(String(255))
    party = Column(String(255))
    party_short = Column(String(20))
    total_electors = Column(BigInteger)
    total_votes = Column(BigInteger)
    poll_percent = Column(Numeric(5,2))
    margin = Column(BigInteger)
    margin_percent = Column(Numeric(5,2))
    year = Column(Integer)


class LokhSabhaResult(Base):
    __tablename__ = "lokh_sabha_results"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    pc_name = Column(String(255))
    No = Column(Integer)
    pc_type = Column(String(50))
    State = Column(String(100))
    winning_candidate = Column(String(255))
    party = Column(String(255))
    party_short = Column(String(20))
    total_electors = Column(BigInteger)
    total_votes = Column(BigInteger)
    turnout_percent = Column(Numeric(5,2))
    margin = Column(BigInteger)
    margin_percent = Column(Numeric(5,2))
    year = Column(Integer)
