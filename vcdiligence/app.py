import os
import re
import json
import socket
import datetime
import threading
from typing import Optional
from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException, status, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Local imports
from vcdiligence.database import (
    init_db, get_db, SessionLocal, User, Organization, Report, Task, AuditLog,
    ReportChange, Decision, PrecisionBenchmark, CompanyListing, ListingInterest
)
from vcdiligence.security import hash_password, verify_password, create_access_token
from vcdiligence.auth import get_current_user, require_admin
from vcdiligence.validator import validate_url_for_ssrf, check_rate_limit
from vcdiligence.logging_config import logger
from vcdiligence.scraper import SmartScraper
from vcdiligence.parser import parse_report_meta
from vcdiligence.public_apis import get_all_public_insights
from vcdiligence.pdf_generator import generate_report_pdf
from vcdiligence.crew import MarketResearchCrew
from vcdiligence.tasks import run_due_diligence_task

app = FastAPI(title="DealScout AI — Enterprise Due Diligence")

# Enable CORS for easier client integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom Global Exception Handler to prevent raw tracebacks in response
@app.exception_handler(Exception)
def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception on {request.url.path}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please contact system administrator."}
    )

# Cleanup hung/active tasks on startup & start Scheduler
@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()
    try:
        # Cleanup hung tasks on server startup unconditionally (Celery is replaced by BackgroundTasks)
        hung_tasks = db.query(Task).filter(Task.status.in_(["starting", "scraping", "analyzing"])).all()
        for t in hung_tasks:
            t.status = "failed"
            t.message = "Task interrupted due to server reboot. Please try running again."
        db.commit()
        if hung_tasks:
            logger.info(f"Reset {len(hung_tasks)} hung tasks to failed status on startup.")

        # Start APScheduler for background continuous monitoring
        from apscheduler.schedulers.background import BackgroundScheduler
        from vcdiligence.monitoring import run_continuous_monitoring_job, refresh_ofac_local_list

        scheduler = BackgroundScheduler()
        interval_hours = int(os.getenv("MONITORING_JOB_INTERVAL_HOURS", "24"))
        scheduler.add_job(run_continuous_monitoring_job, "interval", hours=interval_hours, id="continuous_monitoring")

        # Register weekly OFAC list download job (every Sunday at midnight)
        scheduler.add_job(refresh_ofac_local_list, "cron", day_of_week="sun", hour=0, minute=0, id="ofac_weekly_refresh")

        scheduler.start()
        logger.info(f"APScheduler started. Configured monitoring job to run every {interval_hours} hours, and weekly OFAC list refresh.")
    except Exception as e:
        logger.error(f"Error during startup initialization: {str(e)}")
    finally:
        db.close()

import uuid
from vcdiligence.database import Testimonial, ErrorReport

# Pydantic Schemas
class AnalyzeRequest(BaseModel):
    url: Optional[str] = None
    notify_email: Optional[str] = None
    linkedin_url: Optional[str] = None
    receive_whatsapp: Optional[bool] = False
    whatsapp_number: Optional[str] = None

class SearchCompanyRequest(BaseModel):
    company_name: str

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    password: str
    account_type: str # "personal" or "empresa"
    company_name: Optional[str] = None
    company_website: Optional[str] = None
    referred_by_code: Optional[str] = None

class MonitoringConfigRequest(BaseModel):
    enabled: bool
    interval_days: Optional[int] = 7

class DecisionRequest(BaseModel):
    decision: str  # "invertimos", "pasamos", "en_evaluacion"
    notas: Optional[str] = None

class CreateListingRequest(BaseModel):
    report_id: int
    category: str # "investment" or "acquisition"
    visible_name: str
    visible_industry: str
    visible_country: str
    visible_description: str
    show_numerical_score: bool

# ----------------- AUTHENTICATION ENDPOINTS -----------------

@app.post("/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    # Check if user already exists
    existing = db.query(User).filter_by(email=req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    # Resolve referral if code is provided
    referred_by_id = None
    if req.referred_by_code:
        referrer = db.query(User).filter_by(referral_code=req.referred_by_code).first()
        if referrer:
            referred_by_id = referrer.id

    # Create Organization or map to default
    org_id = 1 # default is DealScout Capital
    if req.account_type == "empresa" and req.company_name:
        # Create a new organization for white-labeling
        new_org = Organization(company_name=req.company_name)
        db.add(new_org)
        db.commit()
        db.refresh(new_org)
        org_id = new_org.id

    # Generate unique referral code
    unique_ref = str(uuid.uuid4())[:8].upper()
    while db.query(User).filter_by(referral_code=unique_ref).first():
        unique_ref = str(uuid.uuid4())[:8].upper()

    user = User(
        email=req.email,
        hashed_password=hash_password(req.password),
        role="analista",
        organization_id=org_id,
        account_type=req.account_type,
        company_name=req.company_name,
        company_website=req.company_website,
        referral_code=unique_ref,
        referred_by_id=referred_by_id
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Perform automatic domain verification if company website is provided and it's a company account
    if req.account_type == "empresa" and req.email and req.company_website:
        try:
            # Simple domain extraction from email
            email_domain = req.email.split("@")[-1].lower()
            # Simple domain extraction from website
            web_clean = req.company_website.lower().replace("http://", "").replace("https://", "").replace("www.", "")
            web_domain = web_clean.split("/")[0]

            if email_domain == web_domain and email_domain not in ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com"]:
                user.verified_domain = True
                db.commit()
        except Exception as e:
            logger.error(f"Error checking register domain match: {str(e)}")

    token = create_access_token(data={"sub": user.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "email": user.email,
            "role": user.role,
            "organization_id": user.organization_id,
            "account_type": user.account_type,
            "company_name": user.company_name,
            "company_website": user.company_website,
            "verified_domain": user.verified_domain,
            "verified_by_admin": user.verified_by_admin,
            "referral_code": user.referral_code,
            "enabled_sources": user.enabled_sources or [],
            "analysis_priorities": user.analysis_priorities or [],
            "custom_focus_keywords": user.custom_focus_keywords or ""
        }
    }

@app.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=req.email).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    token = create_access_token(data={"sub": user.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "email": user.email,
            "role": user.role,
            "organization_id": user.organization_id,
            "account_type": user.account_type,
            "company_name": user.company_name,
            "company_website": user.company_website,
            "verified_domain": user.verified_domain,
            "verified_by_admin": user.verified_by_admin,
            "referral_code": user.referral_code,
            "enabled_sources": user.enabled_sources or [],
            "analysis_priorities": user.analysis_priorities or [],
            "custom_focus_keywords": user.custom_focus_keywords or ""
        }
    }

@app.get("/me")
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "account_type": current_user.account_type,
        "company_name": current_user.company_name,
        "company_website": current_user.company_website,
        "verified_domain": current_user.verified_domain,
        "verified_by_admin": current_user.verified_by_admin,
        "referral_code": current_user.referral_code,
        "referred_by_id": current_user.referred_by_id,
        "profile_photo_path": current_user.profile_photo_path,
        "enabled_sources": current_user.enabled_sources or [],
        "analysis_priorities": current_user.analysis_priorities or [],
        "custom_focus_keywords": current_user.custom_focus_keywords or "",
        "organization": {
            "id": org.id,
            "company_name": org.company_name,
            "logo_path": org.logo_path
        } if org else None
    }

# ----------------- TESTIMONIAL ENDPOINTS -----------------

@app.post("/testimonials")
def submit_testimonial(
    comment: str = Form(...),
    share_comment: bool = Form(False),
    share_photo: bool = Form(False),
    share_name: bool = Form(False),
    screenshot: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Form-data feedback submission.
    Rule: Opt-in by default - fields are false unless explicitly selected.
    If comment-only and share_comment is True -> auto-approved (is_approved=True) because text comments don't need manual moderation.
    If screenshot is uploaded -> is_approved is set to False (pending admin review).
    """
    screenshot_path = None
    if screenshot:
        static_screenshots_dir = os.path.join("vcdiligence", "static", "testimonials")
        os.makedirs(static_screenshots_dir, exist_ok=True)
        filename = f"screenshot_{current_user.id}_{screenshot.filename}"
        path_on_disk = os.path.join(static_screenshots_dir, filename)

        try:
            with open(path_on_disk, "wb") as f:
                f.write(screenshot.file.read())
            screenshot_path = f"/static/testimonials/{filename}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save testimonial screenshot: {str(e)}")

    # Text-only testimonial -> auto-approve if commented is shared
    # Screenshot -> always requires approval (is_approved = False initially)
    is_approved = False if screenshot else True

    testimonial = Testimonial(
        user_id=current_user.id,
        comment=comment,
        share_comment=share_comment,
        share_photo=share_photo,
        share_name=share_name,
        screenshot_path=screenshot_path,
        is_approved=is_approved
    )
    db.add(testimonial)
    db.commit()
    db.refresh(testimonial)

    return {
        "status": "success",
        "testimonial_id": testimonial.id,
        "is_approved": testimonial.is_approved
    }

@app.get("/testimonials")
def get_testimonials(db: Session = Depends(get_db)):
    """
    Returns random rotation of approved, opted-in testimonials.
    Does not expose private details unless opted-in.
    """
    import random
    # Select all approved testimonials that at least share comment
    testimonials = db.query(Testimonial).filter_by(is_approved=True, share_comment=True).all()

    output = []
    for t in testimonials:
        item = {
            "comment": t.comment,
            "screenshot_path": t.screenshot_path
        }
        if t.share_name:
            item["user_name"] = t.user.company_name or t.user.email.split("@")[0]
        else:
            item["user_name"] = "Anonymous User"

        if t.share_photo:
            item["profile_photo_path"] = t.user.profile_photo_path
        else:
            item["profile_photo_path"] = None

        output.append(item)

    # Return randomized list
    random.shuffle(output)
    return output

@app.get("/admin/testimonials")
def list_pending_testimonials(current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Lists all testimonials for moderation."""
    testimonials = db.query(Testimonial).order_by(Testimonial.created_at.desc()).all()
    return [
        {
            "id": t.id,
            "email": t.user.email,
            "comment": t.comment,
            "share_comment": t.share_comment,
            "share_photo": t.share_photo,
            "share_name": t.share_name,
            "screenshot_path": t.screenshot_path,
            "is_approved": t.is_approved,
            "created_at": t.created_at.isoformat()
        } for t in testimonials
    ]

@app.post("/admin/testimonials/{id}/approve")
def approve_testimonial(
    id: int,
    approve: bool = Form(...),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Approves or rejects a testimonial."""
    testimonial = db.query(Testimonial).filter_by(id=id).first()
    if not testimonial:
        raise HTTPException(status_code=404, detail="Testimonial not found")

    if approve:
        testimonial.is_approved = True
    else:
        db.delete(testimonial)

    db.commit()
    return {"status": "success", "message": "Testimonial updated successfully"}

# ----------------- ERROR REPORTS ENDPOINTS -----------------

@app.post("/error-reports")
def submit_error_report(
    description: str = Form(...),
    url: Optional[str] = Form(None),
    screenshot: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Submits a user-reported bug or layout issue.
    Saves details in `error_reports` table and notifies administrators by SMTP.
    """
    screenshot_path = None
    if screenshot:
        static_errors_dir = os.path.join("vcdiligence", "static", "errors")
        os.makedirs(static_errors_dir, exist_ok=True)
        filename = f"error_{current_user.id}_{screenshot.filename}"
        path_on_disk = os.path.join(static_errors_dir, filename)

        try:
            with open(path_on_disk, "wb") as f:
                f.write(screenshot.file.read())
            screenshot_path = f"/static/errors/{filename}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save error screenshot: {str(e)}")

    err_report = ErrorReport(
        user_id=current_user.id,
        description=description,
        url=url,
        screenshot_path=screenshot_path
    )
    db.add(err_report)
    db.commit()
    db.refresh(err_report)

    # SMTP Alert Notification
    subject = f"⚠️ [DealScout AI Bug Report] Nuevo problema reportado por {current_user.email}"
    body = (
        f"Se ha recibido un nuevo reporte de error en DealScout AI:\n\n"
        f"Usuario: {current_user.email}\n"
        f"URL/Pantalla: {url or 'No provista'}\n"
        f"Descripción:\n{description}\n\n"
    )
    if screenshot_path:
        body += f"Captura adjunta (ruta relativa): {screenshot_path}\n"

    try:
        from vcdiligence.monitoring import send_smtp_alert
        send_smtp_alert(subject, body)
    except Exception as s_err:
        logger.error(f"Failed to dispatch bug alert SMTP email: {str(s_err)}")

    return {
        "status": "success",
        "error_report_id": err_report.id,
        "message": "Error report submitted successfully and administrators have been notified."
    }

@app.get("/admin/error-reports")
def list_error_reports(current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Exposes all submitted user bug reports to administrators."""
    reports = db.query(ErrorReport).order_by(ErrorReport.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "email": r.user.email if r.user else "Anonymous",
            "description": r.description,
            "url": r.url,
            "screenshot_path": r.screenshot_path,
            "created_at": r.created_at.isoformat()
        } for r in reports
    ]

# ----------------- PUBLIC STATS ENDPOINT -----------------

@app.get("/stats")
def get_public_stats(db: Session = Depends(get_db)):
    """
    Public, read-only endpoint returning global platform statistics:
    - total registered users
    - accounts split (company vs personal)
    - total companies analyzed
    Enforces MIN_USERS_TO_SHOW_STATS (default 20) threshold before returning statistics.
    """
    total_users = db.query(User).count()
    min_users = int(os.getenv("MIN_USERS_TO_SHOW_STATS", "20"))

    if total_users < min_users:
        return {
            "show_stats": False,
            "min_required": min_users,
            "total_users": total_users,
            "message": "Stats are currently hidden because the minimum user threshold is not met."
        }

    company_users = db.query(User).filter_by(account_type="empresa").count()
    personal_users = db.query(User).filter_by(account_type="personal").count()
    analyzed_companies = db.query(Report.domain).distinct().count()

    return {
        "show_stats": True,
        "total_users": total_users,
        "split": {
            "empresa": company_users,
            "personal": personal_users
        },
        "analyzed_companies": analyzed_companies
    }

# ----------------- SETTINGS & WHITE-LABEL ENDPOINTS -----------------

@app.post("/profile/update")
def update_profile(
    company_name: Optional[str] = Form(None),
    company_website: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Updates user profile details (company name, company website, and profile photo).
    Triggers automatic domain verification if the account type is 'empresa'.
    """
    if company_name:
        current_user.company_name = company_name
    if company_website:
        current_user.company_website = company_website

    if photo:
        static_photos_dir = os.path.join("vcdiligence", "static", "profiles")
        os.makedirs(static_photos_dir, exist_ok=True)
        filename = f"user_{current_user.id}_{photo.filename}"
        photo_path = os.path.join(static_photos_dir, filename)

        try:
            with open(photo_path, "wb") as f:
                f.write(photo.file.read())
            current_user.profile_photo_path = f"/static/profiles/{filename}"
            logger.info(f"Profile photo uploaded for user {current_user.id}: {photo_path}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save profile photo: {str(e)}")

    # Automatic domain verification
    if current_user.account_type == "empresa" and current_user.email and current_user.company_website:
        try:
            email_domain = current_user.email.split("@")[-1].lower()
            web_clean = current_user.company_website.lower().replace("http://", "").replace("https://", "").replace("www.", "")
            web_domain = web_clean.split("/")[0]

            if email_domain == web_domain and email_domain not in ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com"]:
                current_user.verified_domain = True
            else:
                current_user.verified_domain = False
        except Exception as e:
            logger.error(f"Error checking profile update domain match: {str(e)}")

    db.commit()
    db.refresh(current_user)

    return {
        "status": "success",
        "company_name": current_user.company_name,
        "company_website": current_user.company_website,
        "profile_photo_path": current_user.profile_photo_path,
        "verified_domain": current_user.verified_domain
    }

@app.post("/settings")
def update_settings(
    company_name: Optional[str] = Form(None),
    logo: Optional[UploadFile] = File(None),
    enabled_sources: Optional[str] = Form(None),
    analysis_priorities: Optional[str] = Form(None),
    custom_focus_keywords: Optional[str] = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Saves user priorities, preferred sources, and custom focus keywords.
    Also saves custom logo and organization name if the user is an administrator.
    """
    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Only administrators can modify organization settings (company name, logo)
    if logo and current_user.role != "administrador":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Modifying organization custom logo is restricted to administrators."
        )

    if company_name and company_name != org.company_name:
        if current_user.role != "administrador":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Modifying organization name is restricted to administrators."
            )
        else:
            org.company_name = company_name

    if logo and current_user.role == "administrador":
        # Save custom logo file on disk inside safe static uploads directory
        static_logos_dir = os.path.join("vcdiligence", "static", "logos")
        os.makedirs(static_logos_dir, exist_ok=True)
        filename = f"logo_org_{org.id}_{logo.filename}"
        logo_path = os.path.join(static_logos_dir, filename)

        try:
            with open(logo_path, "wb") as f:
                f.write(logo.file.read())
            org.logo_path = logo_path
            logger.info(f"Custom logo uploaded for organization {org.id}: {logo_path}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save uploaded logo: {str(e)}")

    # Update User analysis preferences
    if enabled_sources is not None:
        try:
            parsed_sources = json.loads(enabled_sources)
            if not isinstance(parsed_sources, list):
                parsed_sources = [parsed_sources]
        except Exception:
            parsed_sources = [s.strip() for s in enabled_sources.split(",") if s.strip()]
        current_user.enabled_sources = parsed_sources

    if analysis_priorities is not None:
        try:
            parsed_priorities = json.loads(analysis_priorities)
            if not isinstance(parsed_priorities, list):
                parsed_priorities = [parsed_priorities]
        except Exception:
            parsed_priorities = [p.strip() for p in analysis_priorities.split(",") if p.strip()]
        current_user.analysis_priorities = parsed_priorities

    if custom_focus_keywords is not None:
        current_user.custom_focus_keywords = custom_focus_keywords

    db.commit()

    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        user_email=current_user.email,
        organization_id=current_user.organization_id,
        action="update_settings",
        target_company=company_name or org.company_name
    )
    db.add(audit)
    db.commit()

    return {
        "status": "success",
        "company_name": org.company_name,
        "logo_path": org.logo_path,
        "enabled_sources": current_user.enabled_sources or [],
        "analysis_priorities": current_user.analysis_priorities or [],
        "custom_focus_keywords": current_user.custom_focus_keywords or ""
    }

# ----------------- ANALYSIS ENDPOINTS (MULTI-TENANT) -----------------

@app.post("/analyze")
def start_analysis(
    req: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    url = req.url.strip() if req.url else None
    extra_ctx = {}

    if not url:
        if req.linkedin_url:
            linkedin_info = SmartScraper.scrape_linkedin(req.linkedin_url)
            url = linkedin_info.get("inferred_url")
            extra_ctx["linkedin_data"] = linkedin_info.get("linkedin_data")
            if not url:
                raise HTTPException(
                    status_code=400,
                    detail="Could not infer company official website from LinkedIn URL. Please provide a URL directly."
                )
        else:
            raise HTTPException(
                status_code=400,
                detail="Either a website URL or a LinkedIn URL must be provided to start analysis."
            )

    if req.linkedin_url and "linkedin_data" not in extra_ctx:
        linkedin_info = SmartScraper.scrape_linkedin(req.linkedin_url)
        extra_ctx["linkedin_data"] = linkedin_info.get("linkedin_data")

    # Block SSRF & validate URL
    validated_url = validate_url_for_ssrf(url)
    domain = SmartScraper.get_domain(validated_url)

    # Multi-tenant isolation: check if organization has completed report
    existing_report = db.query(Report).filter_by(domain=domain, organization_id=current_user.organization_id).first()
    if existing_report:
        # Return completed status immediately using cached database report!
        cached_result = {
            "company_name": existing_report.company_name,
            "domain": domain,
            "company_url": existing_report.url,
            "score": existing_report.score,
            "sub_scores": existing_report.sub_scores,
            "recommendation": existing_report.recommendation,
            "report_md": existing_report.report_md,
            "llm_provider": existing_report.llm_provider,
            "pdf_path": f"/reports/{domain}/pdf"
        }
        # Also ensure a Task exists with completed status
        task_id = f"{current_user.organization_id}_{domain}"
        task = db.query(Task).filter_by(id=task_id).first()
        if not task:
            task = Task(
                id=task_id,
                domain=domain,
                status="completed",
                progress=100,
                message="Loaded cached report from database.",
                result_json=cached_result,
                organization_id=current_user.organization_id
            )
            db.add(task)
            db.commit()
        return {"status": "completed", "task_id": task_id}

    # Check Rate Limit (e.g., maximum 10 analyses per hour per organization)
    check_rate_limit(organization_id=current_user.organization_id, db=db, limit=10, window_minutes=60)

    # Check if task is already running for this organization
    task_id = f"{current_user.organization_id}_{domain}"
    active_task = db.query(Task).filter(
        Task.id == task_id,
        Task.status.in_(["starting", "scraping", "analyzing"])
    ).first()
    if active_task:
        return {"status": "running", "task_id": task_id}

    # Record Audit Log
    audit = AuditLog(
        user_id=current_user.id,
        user_email=current_user.email,
        organization_id=current_user.organization_id,
        action="analyze_startup",
        target_company=domain
    )
    db.add(audit)

    # Create new Task row in Database
    task = db.query(Task).filter_by(id=task_id).first()
    if not task:
        task = Task(
            id=task_id,
            domain=domain,
            status="starting",
            progress=5,
            message="Starting due diligence agent network...",
            organization_id=current_user.organization_id
        )
        db.add(task)
    else:
        task.status = "starting"
        task.progress = 5
        task.message = "Restarting analysis..."
        task.result_json = None
    db.commit()

    # Validate WhatsApp request constraints: Only company accounts with verified_by_admin = True
    if req.receive_whatsapp:
        if current_user.account_type != "empresa" or not current_user.verified_by_admin:
            raise HTTPException(
                status_code=403,
                detail="WhatsApp delivery is restricted to verified company accounts only (verified_by_admin = True)"
            )
        if not req.whatsapp_number:
            raise HTTPException(
                status_code=400,
                detail="WhatsApp number must be provided if WhatsApp delivery is selected"
            )
        extra_ctx["whatsapp_delivery"] = {
            "whatsapp_number": req.whatsapp_number,
            "user_email": current_user.email
        }

    # Trigger background task natively using FastAPI's BackgroundTasks
    background_tasks.add_task(
        run_due_diligence_task,
        domain=domain,
        url=validated_url,
        org_id=current_user.organization_id,
        user_id=current_user.id,
        user_email=current_user.email,
        extra_context=extra_ctx if extra_ctx else None,
        notify_email=req.notify_email,
        user_enabled_sources=current_user.enabled_sources,
        user_priorities=current_user.analysis_priorities,
        custom_focus_keywords=current_user.custom_focus_keywords
    )

    return {"status": "running", "task_id": task_id}


@app.post("/search-company")
def search_company(
    req: SearchCompanyRequest,
    current_user: User = Depends(get_current_user)
):
    from urllib.parse import urlparse
    query = f"{req.company_name} official website"
    results = SmartScraper.search_duckduckgo(query, count=5)

    candidates = []
    seen_domains = set()

    for r in results:
        link = r.get("link", "")
        if not link:
            continue

        try:
            domain = SmartScraper.get_domain(link)
        except Exception:
            continue

        if not domain or domain in seen_domains:
            continue

        # Ignore social media and directories
        if any(ignored in domain for ignored in ["linkedin.com", "crunchbase.com", "wikipedia.org", "twitter.com", "facebook.com", "youtube.com", "github.com"]):
            continue

        seen_domains.add(domain)

        # Determine candidate name from search result title
        title = r.get("title", "")
        name = req.company_name
        if title:
            # Clean up the name part from title
            name_part = title.split("|")[0].split("-")[0].strip()
            if name_part:
                name = name_part

        # canonical base url
        parsed_url = urlparse(link)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        candidates.append({
            "name": name,
            "url": base_url,
            "domain": domain,
            "favicon": f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
        })

        if len(candidates) >= 3:
            break

    # Fallback if no clean candidate found
    if not candidates:
        domain = f"{req.company_name.lower().replace(' ', '')}.com"
        candidates.append({
            "name": req.company_name,
            "url": f"https://{domain}",
            "domain": domain,
            "favicon": f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
        })

    return {"options": candidates}


@app.post("/analyze/upload")
def upload_and_analyze(
    background_tasks: BackgroundTasks,
    pitch_deck: UploadFile = File(...),
    url: Optional[str] = Form(None),
    notify_email: Optional[str] = Form(None),
    receive_whatsapp: Optional[bool] = Form(False),
    whatsapp_number: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    extra_ctx = {}
    if receive_whatsapp:
        if current_user.account_type != "empresa" or not current_user.verified_by_admin:
            raise HTTPException(
                status_code=403,
                detail="WhatsApp delivery is restricted to verified company accounts only (verified_by_admin = True)"
            )
        if not whatsapp_number:
            raise HTTPException(
                status_code=400,
                detail="WhatsApp number must be provided if WhatsApp delivery is selected"
            )
        extra_ctx["whatsapp_delivery"] = {
            "whatsapp_number": whatsapp_number,
            "user_email": current_user.email
        }

    # Save the file temporarily
    temp_dir = os.path.join("vcdiligence", "static", "uploads")
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, f"deck_{current_user.organization_id}_{pitch_deck.filename}")

    try:
        with open(file_path, "wb") as f:
            f.write(pitch_deck.file.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload pitch deck: {str(e)}")

    # Extract text from pitch deck
    text = ""
    ext = os.path.splitext(pitch_deck.filename)[1].lower()
    if ext == ".pdf":
        text = SmartScraper.extract_text_from_pdf(file_path)
    elif ext in [".pptx", ".ppt"]:
        text = SmartScraper.extract_text_from_pptx(file_path)
    else:
        # cleanup temporary file
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="Invalid file format. Only PDF and PPTX/PPT are supported.")

    # Clean up the temporary file after text extraction to keep workspace clean
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass

    # Find website URL if not explicitly provided
    validated_url = None
    if url:
        validated_url = validate_url_for_ssrf(url.strip())
    else:
        inferred_url = SmartScraper.extract_url_from_text(text)
        if inferred_url:
            validated_url = validate_url_for_ssrf(inferred_url)
        else:
            # Try to infer from filename as last resort fallback
            name_fallback = os.path.splitext(pitch_deck.filename)[0].lower()
            name_fallback = re.sub(r'[^a-z0-9]', '', name_fallback).replace("pitchdeck", "").replace("deck", "").replace("pitch", "")
            if name_fallback and len(name_fallback) > 1:
                validated_url = validate_url_for_ssrf(f"https://{name_fallback}.com")
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Could not automatically find any website URL inside the pitch deck. Please provide the company URL manually."
                )

    domain = SmartScraper.get_domain(validated_url)

    # Isolation / check if report exists
    existing_report = db.query(Report).filter_by(domain=domain, organization_id=current_user.organization_id).first()
    if existing_report:
        cached_result = {
            "company_name": existing_report.company_name,
            "domain": domain,
            "company_url": existing_report.url,
            "score": existing_report.score,
            "sub_scores": existing_report.sub_scores,
            "recommendation": existing_report.recommendation,
            "report_md": existing_report.report_md,
            "llm_provider": existing_report.llm_provider,
            "pdf_path": f"/reports/{domain}/pdf"
        }
        task_id = f"{current_user.organization_id}_{domain}"
        task = db.query(Task).filter_by(id=task_id).first()
        if not task:
            task = Task(
                id=task_id,
                domain=domain,
                status="completed",
                progress=100,
                message="Loaded cached report from database.",
                result_json=cached_result,
                organization_id=current_user.organization_id
            )
            db.add(task)
            db.commit()
        return {"status": "completed", "task_id": task_id}

    check_rate_limit(organization_id=current_user.organization_id, db=db, limit=10, window_minutes=60)

    task_id = f"{current_user.organization_id}_{domain}"
    active_task = db.query(Task).filter(
        Task.id == task_id,
        Task.status.in_(["starting", "scraping", "analyzing"])
    ).first()
    if active_task:
        return {"status": "running", "task_id": task_id}

    # Record Audit Log
    audit = AuditLog(
        user_id=current_user.id,
        user_email=current_user.email,
        organization_id=current_user.organization_id,
        action="analyze_pitch_deck",
        target_company=domain
    )
    db.add(audit)

    task = db.query(Task).filter_by(id=task_id).first()
    if not task:
        task = Task(
            id=task_id,
            domain=domain,
            status="starting",
            progress=5,
            message="Starting due diligence from pitch deck...",
            organization_id=current_user.organization_id
        )
        db.add(task)
    else:
        task.status = "starting"
        task.progress = 5
        task.message = "Restarting analysis from pitch deck..."
        task.result_json = None
    db.commit()

    # Append pitch deck text to extra_ctx
    if text:
        extra_ctx["pitch_deck_text"] = text

    # Trigger background tasks
    background_tasks.add_task(
        run_due_diligence_task,
        domain=domain,
        url=validated_url,
        org_id=current_user.organization_id,
        user_id=current_user.id,
        user_email=current_user.email,
        extra_context=extra_ctx if extra_ctx else None,
        notify_email=notify_email,
        user_enabled_sources=current_user.enabled_sources,
        user_priorities=current_user.analysis_priorities,
        custom_focus_keywords=current_user.custom_focus_keywords
    )

    return {"status": "running", "task_id": task_id}


@app.get("/status/{task_id}")
def get_status(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Get status of task. Enforce tenant isolation.
    """
    task = db.query(Task).filter_by(id=task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return {
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
        "result": task.result_json
    }

# ----------------- REPORTS & MANAGEMENT ENDPOINTS -----------------

@app.get("/reports")
def list_reports(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List all reports for the user's organization."""
    reports = db.query(Report).filter_by(organization_id=current_user.organization_id).order_by(Report.score.desc()).all()
    return [
        {
            "id": r.id,
            "domain": r.domain,
            "company_name": r.company_name,
            "url": r.url,
            "score": r.score,
            "sub_scores": r.sub_scores,
            "recommendation": r.recommendation,
            "created_at": r.created_at.isoformat()
        } for r in reports
    ]

@app.get("/reports/{domain}/pdf")
def get_pdf_report(domain: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Serves the generated PDF report. Enforces tenant isolation."""
    report = db.query(Report).filter_by(domain=domain, organization_id=current_user.organization_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    pdf_path = report.pdf_path
    if not pdf_path or not os.path.exists(pdf_path):
        # Regenerate PDF on the fly if file is missing
        org = db.query(Organization).filter_by(id=current_user.organization_id).first()
        org_name = org.company_name if org else "DealScout Capital"
        logo_path = org.logo_path if org else None

        report_data_dict = {
            "domain": report.domain,
            "company_name": report.company_name,
            "company_url": report.url,
            "score": report.score,
            "recommendation": report.recommendation,
            "sub_scores": report.sub_scores,
            "report_md": report.report_md
        }
        pdf_path = generate_report_pdf(
            report_data=report_data_dict,
            organization_name=org_name,
            logo_path=logo_path
        )
        report.pdf_path = pdf_path
        db.commit()

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"{report.company_name}_due_diligence.pdf"
    )

@app.get("/compare")
def compare_reports(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Returns side-by-side comparison payload for organization's reports."""
    reports = db.query(Report).filter_by(organization_id=current_user.organization_id).order_by(Report.score.desc()).all()
    return {
        "organization": current_user.organization_id,
        "reports": [
            {
                "company_name": r.company_name,
                "domain": r.domain,
                "score": r.score,
                "sub_scores": r.sub_scores,
                "recommendation": r.recommendation,
                "created_at": r.created_at.isoformat()
            } for r in reports
        ]
    }

# ----------------- CONTINUOUS MONITORING ENDPOINTS -----------------

@app.post("/reports/{domain}/monitoring")
def configure_monitoring(
    domain: str,
    req: MonitoringConfigRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Configures monitoring frequency and enables/disables monitoring for a specific startup."""
    report = db.query(Report).filter_by(domain=domain, organization_id=current_user.organization_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    report.monitoring_enabled = req.enabled
    report.monitoring_interval_days = req.interval_days
    db.commit()

    logger.info(f"Monitoring updated for report {domain}: enabled={req.enabled}, interval={req.interval_days} days.")
    return {
        "status": "success",
        "domain": domain,
        "monitoring_enabled": report.monitoring_enabled,
        "monitoring_interval_days": report.monitoring_interval_days
    }

@app.get("/reports/{domain}/monitoring")
def get_monitoring_history(
    domain: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieves current monitoring settings and historical detected changes (alerts)."""
    report = db.query(Report).filter_by(domain=domain, organization_id=current_user.organization_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    changes = db.query(ReportChange).filter_by(report_id=report.id).order_by(ReportChange.created_at.desc()).all()

    return {
        "domain": domain,
        "monitoring_enabled": report.monitoring_enabled,
        "monitoring_interval_days": report.monitoring_interval_days,
        "last_monitored_at": report.last_monitored_at.isoformat() if report.last_monitored_at else None,
        "changes": [
            {
                "id": c.id,
                "change_type": c.change_type,
                "description": c.description,
                "old_value": c.old_value,
                "new_value": c.new_value,
                "created_at": c.created_at.isoformat()
            } for c in changes
        ]
    }

# ----------------- DECISION CALIBRATION ENDPOINTS -----------------

@app.post("/reports/{domain}/decision")
def register_decision(
    domain: str,
    req: DecisionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Allows an analyst to register a final investment decision for a generated report."""
    report = db.query(Report).filter_by(domain=domain, organization_id=current_user.organization_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if req.decision not in ["invertimos", "pasamos", "en_evaluacion"]:
        raise HTTPException(status_code=400, detail="Invalid decision. Must be 'invertimos', 'pasamos' or 'en_evaluacion'")

    # Upsert decision
    dec = db.query(Decision).filter_by(report_id=report.id, organization_id=current_user.organization_id).first()
    if not dec:
        dec = Decision(
            report_id=report.id,
            organization_id=current_user.organization_id,
            decision=req.decision,
            notas=req.notas,
            user_id=current_user.id
        )
        db.add(dec)
    else:
        dec.decision = req.decision
        dec.notas = req.notas
        dec.user_id = current_user.id
        dec.timestamp = datetime.datetime.utcnow()
    db.commit()

    # Record Audit Log
    audit = AuditLog(
        user_id=current_user.id,
        user_email=current_user.email,
        organization_id=current_user.organization_id,
        action="register_decision",
        target_company=domain
    )
    db.add(audit)
    db.commit()

    logger.info(f"Decision registered for report {domain}: decision={req.decision}")
    return {
        "status": "success",
        "domain": domain,
        "decision": dec.decision,
        "notas": dec.notas
    }

@app.get("/organizations/{org_id}/decision-stats")
def get_decision_stats(
    org_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Returns matching statistics and calibrated category weights for the organization."""
    if current_user.organization_id != org_id:
        raise HTTPException(status_code=403, detail="Access denied")

    decisions = db.query(Decision).filter_by(organization_id=org_id).all()
    if not decisions:
        return {
            "organization_id": org_id,
            "total_decisions": 0,
            "system_overall_match_rate": 1.0,
            "categories": {},
            "calibrated_weights": {
                "market": 0.20,
                "team": 0.20,
                "product": 0.20,
                "traction": 0.20,
                "risk_legal_omissions": 0.20
            }
        }

    categories = ["market", "team", "product", "traction", "risk_legal_omissions"]
    matches = {cat: 0 for cat in categories}
    overall_matches = 0
    total_decisions = len(decisions)

    for d in decisions:
        r = db.query(Report).filter_by(id=d.report_id).first()
        if not r:
            continue

        # Overall match
        # system reco: GO, CONDITIONAL, NO-GO
        # user decision: invertimos, en_evaluacion, pasamos
        is_overall_match = False
        if d.decision == "invertimos" and r.recommendation == "GO":
            is_overall_match = True
        elif d.decision == "pasamos" and r.recommendation == "NO-GO":
            is_overall_match = True
        elif d.decision == "en_evaluacion" and r.recommendation == "CONDITIONAL":
            is_overall_match = True

        if is_overall_match:
            overall_matches += 1

        # Category level match
        if r.sub_scores:
            for cat in categories:
                score_val = r.sub_scores.get(cat, 80)
                is_match = False
                if d.decision == "invertimos" and score_val >= 75:
                    is_match = True
                elif d.decision == "pasamos" and score_val < 60:
                    is_match = True
                elif d.decision == "en_evaluacion" and 60 <= score_val < 75:
                    is_match = True

                if is_match:
                    matches[cat] += 1

    # Match rates
    overall_match_rate = overall_matches / total_decisions
    category_match_rates = {}
    raw_weights = {}
    total_weight_sum = 0.0

    for cat in categories:
        rate = matches[cat] / total_decisions
        category_match_rates[cat] = rate

        # Calculate raw weights with smoothing
        w = 0.1 + 0.9 * rate
        raw_weights[cat] = w
        total_weight_sum += w

    # Normalize weights
    normalized_weights = {cat: w / total_weight_sum for cat, w in raw_weights.items()}

    return {
        "organization_id": org_id,
        "total_decisions": total_decisions,
        "system_overall_match_rate": overall_match_rate,
        "categories": {
            cat: {
                "matches": matches[cat],
                "match_rate": category_match_rates[cat],
                "calibrated_weight": normalized_weights[cat]
            } for cat in categories
        },
        "calibrated_weights": normalized_weights
    }

# ----------------- PRECISION BENCHMARK ENDPOINTS -----------------

@app.get("/admin/benchmark")
def list_benchmarks(current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Exposes precision benchmark scorecard table. Restricted to administrator role only."""
    benchmarks = db.query(PrecisionBenchmark).order_by(PrecisionBenchmark.created_at.desc()).all()
    return [
        {
            "id": b.id,
            "startup_name": b.startup_name,
            "url": b.url,
            "score": b.score,
            "recommendation": b.recommendation,
            "known_outcome": b.known_outcome,
            "matched": b.matched,
            "created_at": b.created_at.isoformat()
        } for b in benchmarks
    ]

# ----------------- DIRECTORY / FOUNDER LISTINGS ENDPOINTS -----------------

@app.post("/listings")
def create_or_update_listing(req: CreateListingRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Creates or updates a company listing for a founder.
    The report belongs to the founder's organization.
    """
    # Enforce tenant isolation / check that report belongs to user's organization
    report = db.query(Report).filter_by(id=req.report_id, organization_id=current_user.organization_id).first()
    if not report:
        raise HTTPException(status_code=403, detail="Report not found or does not belong to your organization")

    if req.category not in ["investment", "acquisition"]:
        raise HTTPException(status_code=400, detail="Invalid category. Must be 'investment' or 'acquisition'")

    # Generate slug from visible_name (clean it for URL friendliness)
    # Ensure slug is unique by appending suffix if exists
    base_slug = re.sub(r'[^a-z0-9]+', '-', req.visible_name.lower()).strip('-')
    if not base_slug:
        base_slug = "company"
    slug = base_slug
    counter = 1
    while db.query(CompanyListing).filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    # Check if a listing already exists for this report
    listing = db.query(CompanyListing).filter_by(report_id=req.report_id).first()
    if listing:
        # Update existing listing
        listing.category = req.category
        listing.visible_name = req.visible_name
        listing.visible_industry = req.visible_industry
        listing.visible_country = req.visible_country
        listing.visible_description = req.visible_description
        listing.show_numerical_score = req.show_numerical_score
        # Keep status as pending_review or reset? Usually reset to pending_review for moderation safety on edit
        listing.status = "pending_review"
    else:
        # Create new listing
        listing = CompanyListing(
            report_id=req.report_id,
            user_id=current_user.id,
            category=req.category,
            slug=slug,
            visible_name=req.visible_name,
            visible_industry=req.visible_industry,
            visible_country=req.visible_country,
            visible_description=req.visible_description,
            show_numerical_score=req.show_numerical_score,
            status="pending_review"
        )
        db.add(listing)

    db.commit()
    db.refresh(listing)

    return {
        "status": "success",
        "listing_id": listing.id,
        "slug": listing.slug,
        "listing_status": listing.status
    }

@app.get("/listings")
def list_public_listings(
    industry: Optional[str] = None,
    country: Optional[str] = None,
    category: Optional[str] = None,
    min_score: Optional[int] = None,
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    Public directory of approved, non-expired company listings.
    Supports filters: industry, country, category, min_score.
    Includes simple pagination.
    """
    now = datetime.datetime.utcnow()
    query = db.query(CompanyListing).join(Report, CompanyListing.report_id == Report.id).filter(
        CompanyListing.status == "approved",
        CompanyListing.expires_at > now
    )

    if industry:
        query = query.filter(CompanyListing.visible_industry.ilike(f"%{industry}%"))
    if country:
        query = query.filter(CompanyListing.visible_country.ilike(f"%{country}%"))
    if category:
        query = query.filter(CompanyListing.category == category)
    if min_score is not None:
        query = query.filter(Report.score >= min_score)

    total = query.count()
    offset = (page - 1) * limit
    listings = query.order_by(CompanyListing.approved_at.desc()).offset(offset).limit(limit).all()

    output = []
    for lst in listings:
        score_display = None
        qualitative_badge = "Alto potencial"
        if lst.report.score >= 85:
            qualitative_badge = "Excelente potencial"
        elif lst.report.score < 70:
            qualitative_badge = "Potencial emergente"

        if lst.show_numerical_score:
            score_display = lst.report.score

        output.append({
            "id": lst.id,
            "slug": lst.slug,
            "visible_name": lst.visible_name,
            "visible_industry": lst.visible_industry,
            "visible_country": lst.visible_country,
            "visible_description": lst.visible_description,
            "category": lst.category,
            "score": score_display,
            "qualitative_badge": qualitative_badge,
            "verified": lst.user.verified_by_admin,
            "created_at": lst.created_at.isoformat(),
            "expires_at": lst.expires_at.isoformat() if lst.expires_at else None
        })

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "listings": output
    }

@app.get("/admin/listings")
def list_admin_listings(current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Admin-only endpoint to view all listings and manage their moderation.
    """
    listings = db.query(CompanyListing).order_by(CompanyListing.created_at.desc()).all()
    output = []
    for lst in listings:
        output.append({
            "id": lst.id,
            "slug": lst.slug,
            "visible_name": lst.visible_name,
            "visible_industry": lst.visible_industry,
            "visible_country": lst.visible_country,
            "visible_description": lst.visible_description,
            "category": lst.category,
            "score": lst.report.score,
            "status": lst.status,
            "created_at": lst.created_at.isoformat(),
            "expires_at": lst.expires_at.isoformat() if lst.expires_at else None
        })
    return output

@app.post("/admin/listings/{id}/approve")
def approve_listing(
    id: int,
    approve: bool = Form(...),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Approves or rejects a company listing.
    When approved, sets:
      - approved_at = now
      - expires_at = now + LISTING_EXPIRY_DAYS
    """
    listing = db.query(CompanyListing).filter_by(id=id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if approve:
        expiry_days = int(os.getenv("LISTING_EXPIRY_DAYS", "60"))
        now = datetime.datetime.utcnow()
        listing.status = "approved"
        listing.approved_at = now
        listing.expires_at = now + datetime.timedelta(days=expiry_days)
    else:
        listing.status = "rejected"

    db.commit()
    db.refresh(listing)

    return {
        "status": "success",
        "listing_id": listing.id,
        "listing_status": listing.status,
        "expires_at": listing.expires_at.isoformat() if listing.expires_at else None
    }

@app.post("/listings/{id}/renew")
def renew_listing(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Allows a founder to renew their listing, extending the expiration date by LISTING_EXPIRY_DAYS.
    """
    listing = db.query(CompanyListing).filter_by(id=id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    # Only listing owner can renew
    if listing.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not own this listing")

    expiry_days = int(os.getenv("LISTING_EXPIRY_DAYS", "60"))
    now = datetime.datetime.utcnow()
    # Renew for another 60 days from now, and set status back to approved if it was hidden/expired
    listing.expires_at = now + datetime.timedelta(days=expiry_days)
    if listing.status == "rejected":
        listing.status = "pending_review"  # Force re-moderation on rejected
    else:
        listing.status = "approved"  # Reactivate directly if it was expired or approved

    db.commit()
    db.refresh(listing)

    return {
        "status": "success",
        "expires_at": listing.expires_at.isoformat(),
        "listing_status": listing.status
    }

@app.get("/empresa/{slug}")
def view_individual_listing(slug: str, db: Session = Depends(get_db)):
    """
    Serves a simple HTML response for the individual public startup listing page,
    with Open Graph meta tags.
    """
    listing = db.query(CompanyListing).filter_by(slug=slug).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Startup not found")

    # Only show approved, non-expired listings publicly, UNLESS it's an admin or the owner (we'll keep it simple: publicly only approved & non-expired)
    now = datetime.datetime.utcnow()
    is_active = (listing.status == "approved" and listing.expires_at and listing.expires_at > now)
    if not is_active:
         raise HTTPException(status_code=403, detail="This listing is currently inactive or under review")

    # Qual badge calculation
    qualitative_badge = "Alto potencial"
    if listing.report.score >= 85:
        qualitative_badge = "Excelente potencial"
    elif listing.report.score < 70:
        qualitative_badge = "Potencial emergente"

    score_val = f"{listing.report.score}/100" if listing.show_numerical_score else qualitative_badge

    # Read from the actual template file to avoid dead/unused code!
    template_path = os.path.join(os.path.dirname(__file__), "templates", "empresa.html")
    if not os.path.exists(template_path):
        raise HTTPException(status_code=500, detail="Template empresa.html not found on disk")

    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Simple placeholder substitution matching template
    html_content = html_content.replace("{{ name }}", listing.visible_name)
    html_content = html_content.replace("{{ score }}", score_val)
    html_content = html_content.replace("{{ description }}", listing.visible_description)
    html_content = html_content.replace("{{ slug }}", listing.slug)
    html_content = html_content.replace("{{ industry }}", listing.visible_industry)
    html_content = html_content.replace("{{ country }}", listing.visible_country)

    category_val = "Buscando inversión" if listing.category == "investment" else "Abierto a conversaciones de adquisición"
    html_content = html_content.replace("{% if category == \"investment\" %}Buscando inversión{% else %}Abierto a conversaciones de adquisición{% endif %}", category_val)

    verified_val = "<span class='bg-cyan-500/15 text-cyan-400 text-[10px] uppercase font-bold px-2 py-0.5 rounded'>✔ Verificado</span>" if listing.user.verified_by_admin else ""
    html_content = html_content.replace("{% if verified %}\n                        <span class='bg-cyan-500/15 text-cyan-400 text-[10px] uppercase font-bold px-2 py-0.5 rounded'>✔ Verificado</span>\n                        {% endif %}", verified_val)
    html_content = html_content.replace("{% if verified %}\r\n                        <span class='bg-cyan-500/15 text-cyan-400 text-[10px] uppercase font-bold px-2 py-0.5 rounded'>✔ Verificado</span>\r\n                        {% endif %}", verified_val)
    html_content = html_content.replace("{% if verified %}\n<span class='bg-cyan-500/15 text-cyan-400 text-[10px] uppercase font-bold px-2 py-0.5 rounded'>✔ Verificado</span>\n{% endif %}", verified_val)

    html_content = html_content.replace("{{ expires_at }}", listing.expires_at.strftime('%Y-%m-%d'))
    html_content = html_content.replace("{{ listing_id }}", str(listing.id))

    return HTMLResponse(content=html_content)

@app.get("/empresa/{slug}/badge")
def view_listing_badge(slug: str, db: Session = Depends(get_db)):
    """
    Generates and returns an SVG image badge of the company's score/qualitative evaluation.
    """
    listing = db.query(CompanyListing).filter_by(slug=slug).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Startup not found")

    qualitative_badge = "Alto potencial"
    if listing.report.score >= 85:
        qualitative_badge = "Excelente potencial"
    elif listing.report.score < 70:
        qualitative_badge = "Potencial emergente"

    score_val = f"{listing.report.score}/100" if listing.show_numerical_score else qualitative_badge

    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="400" height="150" viewBox="0 0 400 150">
  <defs>
    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#0f172a;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#1e293b;stop-opacity:1" />
    </linearGradient>
    <linearGradient id="textGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" style="stop-color:#22d3ee;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#34d399;stop-opacity:1" />
    </linearGradient>
  </defs>
  <rect width="400" height="150" rx="15" fill="url(#grad)" stroke="#334155" stroke-width="2"/>
  <text x="25" y="45" font-family="'Helvetica Neue', Helvetica, Arial, sans-serif" font-size="20" font-weight="bold" fill="url(#textGrad)">{listing.visible_name}</text>
  <text x="25" y="70" font-family="'Helvetica Neue', Helvetica, Arial, sans-serif" font-size="12" fill="#94a3b8">{listing.visible_industry} • {listing.visible_country}</text>
  <rect x="25" y="90" width="350" height="40" rx="8" fill="#020617" stroke="#1e293b" stroke-width="1"/>
  <text x="40" y="115" font-family="'Helvetica Neue', Helvetica, Arial, sans-serif" font-size="12" font-weight="bold" fill="#94a3b8">Investor Readiness Score:</text>
  <text x="360" y="116" font-family="'Helvetica Neue', Helvetica, Arial, sans-serif" font-size="16" font-weight="extrabold" fill="#22d3ee" text-anchor="end">{score_val}</text>
</svg>"""

    return HTMLResponse(content=svg_content, media_type="image/svg+xml")

@app.post("/listings/{id}/interest")
def express_interest_on_listing(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Submits an expression of interest to the founder of a listing.
    Visible only for authenticated users (the route is protected).
    """
    if current_user.account_type != "personal" and current_user.role != "administrador":
        raise HTTPException(status_code=403, detail="Only VCs, investors or administrators can express interest in listings")

    # Restrict button "Me interesa" to VC/investor users. In our roles: "analista" represents VC, but we also check if they are the owner of listing to prevent self-interest.
    listing = db.query(CompanyListing).filter_by(id=id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if listing.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot show interest in your own listing")

    # Guard each expression of interest in the `listing_interests` table
    interest = db.query(ListingInterest).filter_by(listing_id=id, vc_user_id=current_user.id).first()
    if interest:
        raise HTTPException(status_code=400, detail="You have already registered interest in this listing")

    interest = ListingInterest(listing_id=id, vc_user_id=current_user.id)
    db.add(interest)
    db.commit()

    # SMTP Alert Notification (Notify the founder with details of who showed interest)
    founder = listing.user
    subject = f"🔥 [DealScout AI] Un inversionista se ha interesado en {listing.visible_name}!"
    body = (
        f"Hola {founder.email},\n\n"
        f"¡Grandes noticias! Un inversionista ha manifestado interés en tu empresa '{listing.visible_name}' a través de DealScout AI.\n\n"
        f"Detalles del inversionista:\n"
        f"- Nombre / Organización: {current_user.company_name or 'Inversionista Independiente'}\n"
        f"- Correo de contacto: {current_user.email}\n\n"
        f"Ahora puedes decidir si deseas ponerte en contacto directamente con ellos respondiendo a este correo.\n\n"
        f"Atentamente,\n"
        f"El equipo de DealScout AI"
    )

    try:
        from vcdiligence.monitoring import send_smtp_alert
        send_smtp_alert(subject, body)
    except Exception as s_err:
        logger.error(f"Failed to dispatch interest alert SMTP email: {str(s_err)}")

    return {
        "status": "success",
        "message": "Interest registered successfully. Founder has been notified."
    }

# ----------------- ADMIN DIRECT USER VERIFICATION ENDPOINT -----------------

@app.post("/admin/users/{id}/verify-by-admin")
def toggle_admin_verification(
    id: int,
    verified: bool = Form(...),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Allows an administrator to manually mark a company account as verified_by_admin."""
    user = db.query(User).filter_by(id=id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.verified_by_admin = verified
    db.commit()
    db.refresh(user)

    return {
        "status": "success",
        "user_id": user.id,
        "verified_by_admin": user.verified_by_admin
    }

@app.get("/admin/users")
def list_users_for_admin(current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Allows an admin to view all registered users to manage manual verification."""
    users = db.query(User).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "account_type": u.account_type,
            "company_name": u.company_name,
            "company_website": u.company_website,
            "verified_domain": u.verified_domain,
            "verified_by_admin": u.verified_by_admin,
            "referral_code": u.referral_code,
            "created_at": u.created_at.isoformat()
        } for u in users
    ]

# ----------------- DEMO BACKWARD COMPATIBLE & UTILS -----------------

@app.get("/health")
def health_check():
    from vcdiligence.llm_manager import LLMProviderManager
    provider_llm, provider_name = LLMProviderManager.get_llm()
    return {"status": "ok", "provider": provider_name}

@app.get("/")
def get_index():
    index_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Frontend template not found")
    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

# Mount ONLY the safe subfolder containing static uploads to prevent source code leaks!
static_uploads_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_uploads_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_uploads_dir), name="static")

def main():
    import uvicorn
    port = int(os.getenv("PORT", "10000"))
    # Disable reload in production
    is_prod = os.getenv("ENV", "development").lower() == "production"
    reload_setting = not is_prod
    logger.info(f"Starting server on port {port} (reload={reload_setting})")
    uvicorn.run("vcdiligence.app:app", host="0.0.0.0", port=port, reload=reload_setting)

if __name__ == "__main__":
    main()
