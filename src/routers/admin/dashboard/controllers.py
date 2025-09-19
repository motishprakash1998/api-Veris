from sqlalchemy import  func
from sqlalchemy.orm import Session,joinedload
from .schemas import  CommonFilters
from src.routers.employees.models import  Employee ,EmployeeProfile, StatusEnum
from src.routers.election_services.models import  Affidavit,Result,Election,Candidate,Constituency,Party,State



def get_employee_data(db: Session, filters: CommonFilters):
    query = (
        db.query(Employee)
        .join(EmployeeProfile, EmployeeProfile.employee_id == Employee.id)
        .filter(Employee.status == StatusEnum.active)   # ✅ active employees only
    )
    # logging.
    if filters.state_name:
        query = query.filter(EmployeeProfile.state_name == filters.state_name)
    if filters.pc_name:
        query = query.filter(EmployeeProfile.pc_name == filters.pc_name)
    if filters.year:
        query = query.filter(func.extract("year", Employee.created_at) == filters.year)

    return query.all()


def get_waiting_employee_data(db: Session, filters: CommonFilters):
    query = (
        db.query(Employee)
        .join(EmployeeProfile, EmployeeProfile.employee_id == Employee.id)
        .filter(Employee.status == StatusEnum.waiting)  # ✅ waiting employees only
    )

    if filters.state_name:
        query = query.filter(EmployeeProfile.state_name == filters.state_name)
    if filters.pc_name:
        query = query.filter(EmployeeProfile.pc_name == filters.pc_name)
    if filters.year:
        query = query.filter(func.extract("year", Employee.created_at) == filters.year)

    return query.all()

# -------------------------
# Get ECI Data
# -------------------------
def get_eci_data(db: Session, filters: CommonFilters):
    query = (
        db.query(Result)
        .join(Result.election)
        .join(Election.constituency)
        .join(Constituency.state)
        .join(Result.candidate)
        .join(Candidate.party)
        .options(
            joinedload(Result.election).joinedload(Election.constituency).joinedload(Constituency.state),
            joinedload(Result.candidate).joinedload(Candidate.party),
        )
        .filter(Result.is_deleted == False)  # exclude soft-deleted
    )

    # Apply filters
    if filters.state_name:
        query = query.filter(State.state_name == filters.state_name)
    if filters.pc_name:
        query = query.filter(Constituency.pc_name == filters.pc_name)
    if filters.year:
        query = query.filter(Election.year == filters.year)
    if filters.party_name:
        query = query.filter(Party.party_name == filters.party_name)
    if filters.candidate_name:
        query = query.filter(Candidate.candidate_name == filters.candidate_name)

    return query.all()


# -------------------------
# Get MyNeta Data (Affidavits)
# -------------------------
def get_myneta_data(db: Session, filters: CommonFilters):
    query = db.query(Affidavit)

    # Apply filters
    if filters.state_name:
        query = query.filter(Affidavit.state_name == filters.state_name)
    if filters.pc_name:
        query = query.filter(Affidavit.pc_name == filters.pc_name)
    if filters.year:
        query = query.filter(Affidavit.year == filters.year)
    if filters.party_name:
        query = query.filter(Affidavit.party_name == filters.party_name)
    if filters.candidate_name:
        query = query.filter(Affidavit.candidate_name == filters.candidate_name)

    return query.all()




def get_dashboard_data(db: Session, filters: CommonFilters):
    """
    Wrapper function to fetch all datasets for the dashboard
    by calling existing helper functions.
    """

    active_employees = get_employee_data(db, filters)
    # waiting_employees = get_waiting_employee_data(db, filters)
    # eci_results = get_eci_data(db, filters)
    # myneta_affidavits = get_myneta_data(db, filters)

    return {
        # "eci_data": eci_results,
        # "myneta_data": myneta_affidavits,
        "employee_data": active_employees,
        # "waiting_employee_data": waiting_employees,
    }
