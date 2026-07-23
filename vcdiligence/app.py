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
from vcdiligence.database import init_db, get_db, SessionLocal, User, Organization, Report, Task, AuditLog
from vcdiligence.security import hash_password, verify_password, create_access_token
from vcdiligence.auth import get_current_user, require_admin
from vcdiligence.validator import validate_url_for_ssrf, check_rate_limit
from vcdiligence.logging_config import logger
from vcdiligence.scraper import SmartScraper
from vcdiligence.parser import parse_report_meta
from vcdiligence.public_apis import get_all_public_insights
from vcdiligence.pdf_generator import generate_report_pdf
from vcdiligence.crew import MarketResearchCrew

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

# Cleanup hung/active tasks on startup
@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()
    try:
        # If any task was in starting, scraping or analyzing state when server restarted, set it to failed
        hung_tasks = db.query(Task).filter(Task.status.in_(["starting", "scraping", "analyzing"])).all()
        for t in hung_tasks:
            t.status = "failed"
            t.message = "Task interrupted due to server reboot. Please try running again."
        db.commit()
        if hung_tasks:
            logger.info(f"Reset {len(hung_tasks)} hung tasks to failed status on startup.")
    except Exception as e:
        logger.error(f"Error during startup task cleanup: {str(e)}")
    finally:
        db.close()

# Pydantic Schemas
class AnalyzeRequest(BaseModel):
    url: str

class LoginRequest(BaseModel):
    email: str
    password: str

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

def run_due_diligence_task(domain: str, url: str, org_id: int, user_id: int, user_email: str):
    """
    Runs the multi-agent crew in a background task, updating DB Task rows.
    """
    db = SessionLocal()
    try:
        # 1. Update status to scraping
        task = db.query(Task).filter_by(id=f"{org_id}_{domain}").first()
        if task:
            task.status = "scraping"
            task.progress = 15
            task.message = "Scraping startup web presence & checking public records..."
            db.commit()

        # Gather public API insights
        company_name = domain.split('.')[0].capitalize()
        logger.info(f"Running Public API queries for {company_name}")
        public_insights = get_all_public_insights(company_name)
        public_insights_text = json.dumps(public_insights, indent=2)

        # Scrape company landing and internal pages
        payload = SmartScraper.analyze_startup(url)

        internal_pages_text = ""
        for path, content in payload.get("internal_pages", {}).items():
            internal_pages_text += f"\n--- Page: {path} ---\n{content}\n"
        if not internal_pages_text:
            internal_pages_text = "No internal pages found."

        competitors = json.dumps(payload.get("search_insights", {}).get("competitors", []), indent=2)
        pricing_product = json.dumps(payload.get("search_insights", {}).get("pricing_and_product", []), indent=2)
        market_funding = json.dumps(payload.get("search_insights", {}).get("market_and_funding", []), indent=2)
        team_founders = json.dumps(payload.get("search_insights", {}).get("team_and_founders", []), indent=2)

        # 2. Update status to analyzing
        task = db.query(Task).filter_by(id=f"{org_id}_{domain}").first()
        if task:
            task.status = "analyzing"
            task.progress = 40
            task.message = "Coordinating CrewAI multi-agent market, product & omission analysis..."
            db.commit()

        crew_obj = MarketResearchCrew()
        inputs = {
            "company_name": payload.get("company_name", company_name),
            "company_url": payload.get("company_url", url),
            "homepage_summary": payload.get("homepage_summary", "")[:2500],
            "internal_pages_text": internal_pages_text[:2500],
            "competitor_insights": competitors[:2500],
            "pricing_and_product_insights": pricing_product[:2500],
            "market_and_funding_insights": market_funding[:2500],
            "team_and_founders_insights": team_founders[:2500],
            "public_api_insights": public_insights_text[:3500] # Pass public records directly to agents!
        }

        # Run CrewAI kickoff
        result_output = crew_obj.crew().kickoff(inputs=inputs)
        markdown_report = getattr(result_output, "raw", str(result_output))

        # Parse metadata
        score, recommendation, sub_scores = parse_report_meta(markdown_report)

        # Build white-label organization details for PDF
        org = db.query(Organization).filter_by(id=org_id).first()
        org_name = org.company_name if org else "DealScout Capital"
        logo_path = org.logo_path if org else None

        # Generate report data dict
        report_data_dict = {
            "domain": domain,
            "company_name": payload.get("company_name", company_name),
            "company_url": url,
            "score": score,
            "recommendation": recommendation,
            "sub_scores": sub_scores,
            "report_md": markdown_report
        }

        # Generate white-labeled PDF report
        pdf_path = generate_report_pdf(
            report_data=report_data_dict,
            organization_name=org_name,
            logo_path=logo_path
        )

        # 3. Create or update Report in DB
        report = db.query(Report).filter_by(domain=domain, organization_id=org_id).first()
        if not report:
            report = Report(
                domain=domain,
                company_name=company_name,
                url=url,
                score=score,
                sub_scores=sub_scores,
                recommendation=recommendation,
                report_md=markdown_report,
                pdf_path=pdf_path,
                llm_provider=crew_obj.provider_name,
                organization_id=org_id
            )
            db.add(report)
        else:
            report.score = score
            report.sub_scores = sub_scores
            report.recommendation = recommendation
            report.report_md = markdown_report
            report.pdf_path = pdf_path
            report.llm_provider = crew_obj.provider_name
        db.commit()

        # Update Task to completed
        final_data = {
            "company_name": company_name,
            "domain": domain,
            "company_url": url,
            "score": score,
            "recommendation": recommendation,
            "sub_scores": sub_scores,
            "report_md": markdown_report,
            "llm_provider": crew_obj.provider_name,
            "pdf_path": f"/reports/{domain}/pdf"
        }

        task = db.query(Task).filter_by(id=f"{org_id}_{domain}").first()
        if task:
            task.status = "completed"
            task.progress = 100
            task.message = "Analysis successfully completed!"
            task.result_json = final_data
            db.commit()

    except Exception as e:
        logger.error(f"Error running due diligence background task: {str(e)}", exc_info=True)
        task = db.query(Task).filter_by(id=f"{org_id}_{domain}").first()
        if task:
            task.status = "failed"
            task.progress = 0
            task.message = f"Analysis failed: {str(e)}"
            db.commit()
    finally:
        db.close()

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

    # Trigger background thread
    background_tasks.add_task(
        run_due_diligence_task,
        domain=domain,
        url=validated_url,
        org_id=current_user.organization_id,
        user_id=current_user.id,
        user_email=current_user.email
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
