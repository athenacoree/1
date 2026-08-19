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

from sqlalchemy.pool import NullPool

# SQLite-specific arguments (e.g., check_same_thread)
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    engine = create_engine(DATABASE_URL, connect_args=connect_args, poolclass=NullPool)
else:
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String, unique=True, index=True, nullable=False)
    logo_path = Column(String, nullable=True) # For white-label custom logo
    created_at = Column(DateTime, default=utc_now)

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
    created_at = Column(DateTime, default=utc_now)

    # Added fields for validation, landing, and referral
    account_type = Column(String, default="personal", nullable=False) # "personal" or "empresa"
    company_name = Column(String, nullable=True)
    company_website = Column(String, nullable=True)
    verified_domain = Column(Boolean, default=False, nullable=False)
    verified_by_admin = Column(Boolean, default=False, nullable=False)
    profile_photo_path = Column(String, nullable=True)
    referral_code = Column(String, unique=True, index=True, nullable=True)
    referred_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # User analysis preferences
    enabled_sources = Column(JSON, default=list, nullable=True)
    analysis_priorities = Column(JSON, default=list, nullable=True)
    custom_focus_keywords = Column(String, default="", nullable=False)

    organization = relationship("Organization", back_populates="users")

class Testimonial(Base):
    __tablename__ = "testimonials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    comment = Column(Text, nullable=False)
    share_comment = Column(Boolean, default=False, nullable=False)
    share_photo = Column(Boolean, default=False, nullable=False)
    share_name = Column(Boolean, default=False, nullable=False)
    screenshot_path = Column(String, nullable=True)
    is_approved = Column(Boolean, default=False, nullable=False) # screenshot needs manual approval, text comments auto-approve
    created_at = Column(DateTime, default=utc_now)

    user = relationship("User")

class ErrorReport(Base):
    __tablename__ = "error_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    description = Column(Text, nullable=False)
    url = Column(String, nullable=True)
    screenshot_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    user = relationship("User")

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
    screenshot_gallery = Column(JSON, nullable=True)
    hype_qa = Column(JSON, nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now)

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
    created_at = Column(DateTime, default=utc_now)

    report = relationship("Report", back_populates="changes")


class Decision(Base):
    __tablename__ = "decisions"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    decision = Column(String, nullable=False) # "invertimos", "pasamos", "en_evaluacion"
    notas = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    timestamp = Column(DateTime, default=utc_now)

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
    created_at = Column(DateTime, default=utc_now)

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, index=True) # UUID or domain name
    domain = Column(String, index=True, nullable=False)
    status = Column(String, default="starting", nullable=False) # starting, scraping, analyzing, completed, failed
    progress = Column(Integer, default=5, nullable=False)
    message = Column(String, nullable=True)
    result_json = Column(JSON, nullable=True)
    partial_sections = Column(JSON, default=dict, nullable=True)
    hype_qa = Column(JSON, nullable=True)
    language = Column(String, default="es", nullable=False)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now)

    organization = relationship("Organization", back_populates="tasks")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)
    user_email = Column(String, nullable=True)
    organization_id = Column(Integer, nullable=True)
    action = Column(String, nullable=False) # e.g. "analyze_startup", "view_report", "delete_report"
    target_company = Column(String, nullable=True)
    timestamp = Column(DateTime, default=utc_now)

class CompanyListing(Base):
    __tablename__ = "company_listings"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(String, nullable=False) # "investment" or "acquisition"
    slug = Column(String, unique=True, index=True, nullable=False)

    # Visible public details chosen by the founder
    visible_name = Column(String, nullable=False)
    visible_industry = Column(String, nullable=False)
    visible_country = Column(String, nullable=False)
    visible_description = Column(Text, nullable=False)
    show_numerical_score = Column(Boolean, default=False, nullable=False)

    status = Column(String, default="pending_review", nullable=False) # "pending_review", "approved", "rejected"
    created_at = Column(DateTime, default=utc_now)
    approved_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    report = relationship("Report")
    user = relationship("User")

class ListingInterest(Base):
    __tablename__ = "listing_interests"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("company_listings.id"), nullable=False)
    vc_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now)

    listing = relationship("CompanyListing")
    vc_user = relationship("User")

class ApiKeyPool(Base):
    __tablename__ = "api_key_pools"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False)  # "openrouter", "grok", "openai"
    api_key = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    status = Column(String, default="healthy", nullable=False)  # "healthy", "exhausted", "disabled"
    consecutive_failures = Column(Integer, default=0, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    last_failure_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

class PricingPlan(Base):
    __tablename__ = "pricing_plans"

    id = Column(Integer, primary_key=True, index=True)
    plan_type = Column(String, nullable=False)  # "per_analysis", "subscription_monthly", "credit_bundle"
    name = Column(String, nullable=False)
    price_cents = Column(Integer, nullable=False)
    currency = Column(String, default="USD", nullable=False)
    credits_included = Column(Integer, nullable=True)  # only for credit_bundle
    is_active = Column(Boolean, default=False, nullable=False)
    allowed_providers = Column(JSON, default=list, nullable=False)  # e.g., ["stripe", "crypto"]
    created_at = Column(DateTime, default=utc_now, nullable=False)

class UserWallet(Base):
    __tablename__ = "user_wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    credits_balance = Column(Integer, default=0, nullable=False)
    subscription_active = Column(Boolean, default=False, nullable=False)
    subscription_expires_at = Column(DateTime, nullable=True)

    user = relationship("User")

class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("pricing_plans.id"), nullable=False)
    provider = Column(String, nullable=False)  # "stripe" or "crypto"
    external_transaction_id = Column(String, nullable=True)
    amount_cents = Column(Integer, nullable=False)
    status = Column(String, default="pending", nullable=False)  # "pending", "completed", "failed", "refunded"
    created_at = Column(DateTime, default=utc_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User")
    plan = relationship("PricingPlan")

class TokenUsageLog(Base):
    __tablename__ = "token_usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=True)
    agent_name = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    model_name = Column(String, nullable=False)
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

class SystemConfig(Base):
    __tablename__ = "system_configs"

    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=False)
    value_type = Column(String, default="string", nullable=False) # "string", "int", "bool"
    category = Column(String, default="general", nullable=False) # "branding", "llm_budget", "general", "payments"
    description = Column(String, default="", nullable=False)

class ScreenshotCache(Base):
    __tablename__ = "screenshot_caches"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, index=True, nullable=False)
    screenshot_url = Column(String, nullable=False)
    captured_at = Column(DateTime, default=utc_now, nullable=False)

def init_db():
    import os
    import sys
    from alembic.config import Config
    from alembic import command

    # Check if we are in testing environment
    is_testing = os.getenv("TESTING") or "unittest" in sys.modules

    if is_testing:
        # For unit testing, metadata.create_all is safer and faster
        Base.metadata.create_all(bind=engine)
        return

    try:
        # Get root path of the repo where alembic.ini is located
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ini_path = os.path.join(base_dir, "alembic.ini")
        alembic_cfg = Config(ini_path)
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        import traceback
        traceback.print_exc()
        # Fallback to create_all if alembic upgrade fails
        Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
