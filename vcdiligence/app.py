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
    ReportChange, Decision, PrecisionBenchmark
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
        from vcdiligence.celery_app import celery_app
        # Only cleanup hung tasks on server startup if we are running in synchronous eager mode
        if celery_app.conf.task_always_eager:
            hung_tasks = db.query(Task).filter(Task.status.in_(["starting", "scraping", "analyzing"])).all()
            for t in hung_tasks:
                t.status = "failed"
                t.message = "Task interrupted due to server reboot. Please try running again."
            db.commit()
            if hung_tasks:
                logger.info(f"Reset {len(hung_tasks)} hung tasks to failed status on startup.")

        # Start APScheduler for background continuous monitoring
        from apscheduler.schedulers.background import BackgroundScheduler
        from vcdiligence.monitoring import run_continuous_monitoring_job

        scheduler = BackgroundScheduler()
        interval_hours = int(os.getenv("MONITORING_JOB_INTERVAL_HOURS", "24"))
        scheduler.add_job(run_continuous_monitoring_job, "interval", hours=interval_hours, id="continuous_monitoring")
        scheduler.start()
        logger.info(f"APScheduler started. Configured monitoring job to run every {interval_hours} hours.")
    except Exception as e:
        logger.error(f"Error during startup initialization: {str(e)}")
    finally:
        db.close()

# Pydantic Schemas
class AnalyzeRequest(BaseModel):
    url: str

class LoginRequest(BaseModel):
    email: str
    password: str

class MonitoringConfigRequest(BaseModel):
    enabled: bool
    interval_days: Optional[int] = 7

class DecisionRequest(BaseModel):
    decision: str  # "invertimos", "pasamos", "en_evaluacion"
    notas: Optional[str] = None

# ----------------- AUTHENTICATION ENDPOINTS -----------------

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
            "organization_id": user.organization_id
        }
    }

@app.get("/me")
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "organization": {
            "id": org.id,
            "company_name": org.company_name,
            "logo_path": org.logo_path
        } if org else None
    }

# ----------------- SETTINGS & WHITE-LABEL ENDPOINTS -----------------

@app.post("/settings")
def update_settings(
    company_name: str = Form(...),
    logo: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Saves custom logo and organization name. Restricted to administrador.
    """
    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.company_name = company_name

    if logo:
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

    db.commit()

    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        user_email=current_user.email,
        organization_id=current_user.organization_id,
        action="update_settings",
        target_company=company_name
    )
    db.add(audit)
    db.commit()

    return {
        "status": "success",
        "company_name": org.company_name,
        "logo_path": org.logo_path
    }

# ----------------- ANALYSIS ENDPOINTS (MULTI-TENANT) -----------------

@app.post("/analyze")
def start_analysis(
    req: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    url = req.url.strip()

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

    # Trigger Celery asynchronous task
    run_due_diligence_task.delay(
        domain,
        validated_url,
        current_user.organization_id,
        current_user.id,
        current_user.email
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
