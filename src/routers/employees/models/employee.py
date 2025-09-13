import re
import enum
import bcrypt
from sqlalchemy import (
    Column, Integer, String, Date, Enum as SAEnum, ForeignKey, TIMESTAMP, Text,
    Index,Boolean
)
from sqlalchemy.sql import func
from sqlalchemy.orm import validates, relationship, declarative_base

Base = declarative_base()

# =============================
# Enums (match DB enum names)
# =============================
class RoleEnum(enum.Enum):
    employee = "employee"
    superadmin = "superadmin"

class StatusEnum(enum.Enum):
    active = "active"
    inactive = "inactive"
    waiting = "waiting"

class GenderEnum(enum.Enum):
    male = "male"
    female = "female"
    other = "other"


# =============================
# employees
# =============================
class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(SAEnum(RoleEnum, name="role_enum", native_enum=True), nullable=False, default=RoleEnum.employee)
    status = Column(SAEnum(StatusEnum, name="status_enum", native_enum=True), nullable=False, default=StatusEnum.active)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    profile = relationship(
        "EmployeeProfile",
        uselist=False,
        back_populates="employee",
        cascade="all, delete-orphan"
    )
    devices = relationship(
        "EmployeeDevice",
        back_populates="employee",
        cascade="all, delete-orphan"
    )
    reset_tokens = relationship(
        "PasswordResetToken",
        back_populates="employee",
        cascade="all, delete-orphan"
    )

    # ---------- validation & helpers ----------
    @validates("email")
    def validate_email(self, key, email: str):
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email or ""):
            raise ValueError("Invalid email address")
        return email

    def set_password(self, raw_password: str):
        """Hash and set the employee password."""
        self.password_hash = bcrypt.hashpw(
            raw_password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

    def verify_password(self, raw_password: str) -> bool:
        """Verify a password against stored hash."""
        return bcrypt.checkpw(
            raw_password.encode("utf-8"),
            self.password_hash.encode("utf-8")
        )

    def __repr__(self):
        return f"<Employee(id={self.id}, email={self.email}, role={self.role.value})>"


# ✅ Case-insensitive unique email (matches LOWER(email) unique index in SQL)
Index("idx_employees_email_lower", func.lower(Employee.email), unique=True)


# =============================
# employee_profiles (1:1)
# =============================
class EmployeeProfile(Base):
    __tablename__ = "employee_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), unique=True, nullable=False)

    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone_number = Column(String(20), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(SAEnum(GenderEnum, name="gender_enum", native_enum=True), nullable=True)
    address = Column(String(255), nullable=True)
    state = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    pin_code = Column(String(20), nullable=True)
    # ✅ New columns
    state_name = Column(String(150), nullable=True)
    pc_name = Column(String(150), nullable=True)
    profile_path = Column(Text, nullable=False, default="profile_pictures/default.png")

    # No doctor-only fields (specialization, license_number, years_exprience) — removed
    emergency_contact = Column(String(20), nullable=True)

    # 0/1 -> use boolean in DB; here keep int to mirror your Pydantic, or change to Boolean if you prefer
    profile_completed = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationship
    employee = relationship("Employee", back_populates="profile")

    @validates("phone_number", "emergency_contact")
    def validate_phone_e164(self, key, value):
        if value and not re.match(r"^\+?[1-9]\d{1,14}$", value):
            raise ValueError(f"Invalid {key} (must be E.164)")
        return value

    def __repr__(self):
        return f"<EmployeeProfile(id={self.id}, employee_id={self.employee_id}, name={self.first_name} {self.last_name})>"


# =============================
# employee_devices (FCM tokens / sessions)
# =============================
class EmployeeDevice(Base):
    __tablename__ = "employee_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    fcm_token = Column(Text, nullable=False)
    last_seen_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    employee = relationship("Employee", back_populates="devices")

    def __repr__(self):
        return f"<EmployeeDevice(id={self.id}, employee_id={self.employee_id})>"


# =============================
# password_reset_tokens
# =============================
class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    token = Column(Text, nullable=False, unique=True)
    expires_at = Column(TIMESTAMP, nullable=False)
    used_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    employee = relationship("Employee", back_populates="reset_tokens")

    def __repr__(self):
        return f"<PasswordResetToken(id={self.id}, employee_id={self.employee_id})>"
