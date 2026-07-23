import os
import json
import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text, JSON, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Use SQLite by default, save in root folder or inside package
    DATABASE_URL = "sqlite:///vcdiligence.db"

# Some deployment services might provide a postgres:// URL, but SQLAlchemy 1.4+ expects postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# SQLite-specific arguments (e.g., check_same_thread)
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String, unique=True, index=True, nullable=False)
    logo_path = Column(String, nullable=True) # For white-label custom logo
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="organization", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="organization", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="analista", nullable=False) # "analista" or "administrador"
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    organization = relationship("Organization", back_populates="users")

class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String, index=True, nullable=False)
    company_name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    score = Column(Integer, nullable=False)
    sub_scores = Column(JSON, nullable=True) # Dictionary mapping category -> score
    recommendation = Column(String, nullable=False) # GO / CONDITIONAL / NO-GO
    report_md = Column(Text, nullable=False)
    pdf_path = Column(String, nullable=True)
    llm_provider = Column(String, nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Monitoring configuration columns
    monitoring_enabled = Column(Boolean, default=False, nullable=False)
    monitoring_interval_days = Column(Integer, default=7, nullable=False)
    last_monitored_at = Column(DateTime, nullable=True)

    organization = relationship("Organization", back_populates="reports")
    changes = relationship("ReportChange", back_populates="report", cascade="all, delete-orphan")


class ReportChange(Base):
    __tablename__ = "report_changes"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    change_type = Column(String, nullable=False) # "score_change", "sec_edgar", "courtlistener", "github", "general"
    description = Column(Text, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    report = relationship("Report", back_populates="changes")


class Decision(Base):
    __tablename__ = "decisions"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    decision = Column(String, nullable=False) # "invertimos", "pasamos", "en_evaluacion"
    notas = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    report = relationship("Report")
    organization = relationship("Organization")
    user = relationship("User")


class PrecisionBenchmark(Base):
    __tablename__ = "precision_benchmarks"

    id = Column(Integer, primary_key=True, index=True)
    startup_name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    score = Column(Integer, nullable=True)
    recommendation = Column(String, nullable=True)
    known_outcome = Column(String, nullable=False) # "success", "failure", "acquisition"
    matched = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, index=True) # UUID or domain name
    domain = Column(String, index=True, nullable=False)
    status = Column(String, default="starting", nullable=False) # starting, scraping, analyzing, completed, failed
    progress = Column(Integer, default=5, nullable=False)
    message = Column(String, nullable=True)
    result_json = Column(JSON, nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    organization = relationship("Organization", back_populates="tasks")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)
    user_email = Column(String, nullable=True)
    organization_id = Column(Integer, nullable=True)
    action = Column(String, nullable=False) # e.g. "analyze_startup", "view_report", "delete_report"
    target_company = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
