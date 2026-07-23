import os
import json
from vcdiligence.celery_app import celery_app
from vcdiligence.database import SessionLocal, Organization, Report, Task
from vcdiligence.logging_config import logger
from vcdiligence.scraper import SmartScraper
from vcdiligence.parser import parse_report_meta
from vcdiligence.public_apis import get_all_public_insights
from vcdiligence.pdf_generator import generate_report_pdf
from vcdiligence.crew import MarketResearchCrew

# Helper to avoid circular imports later
def get_adjusted_score_for_org(db, org_id: int, sub_scores: dict, default_score: int, default_reco: str):
    """
    Recalculates the overall score based on the organization's historical decisions calibration (if any).
    """
    try:
        from vcdiligence.database import Decision
        decisions = db.query(Decision).filter_by(organization_id=org_id).all()
        if not decisions:
            return default_score, default_reco

        # Default weights
        categories = ["market", "team", "product", "traction", "risk_legal_omissions"]
        matches = {cat: 0 for cat in categories}
        total_decisions = len(decisions)

        for d in decisions:
            # Map user decision to expected score ranges
            # "invertimos" -> high scores (>= 75)
            # "pasamos" -> low scores (< 60)
            # "en_evaluacion" -> medium scores (60 <= score < 75)
            r = db.query(Report).filter_by(id=d.report_id).first()
            if not r or not r.sub_scores:
                continue

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

        # Calculate raw weights (smoothing factor 0.1 to avoid 0 weight)
        raw_weights = {}
        total_weight_sum = 0.0
        for cat in categories:
            match_rate = matches[cat] / total_decisions if total_decisions > 0 else 1.0
            weight = 0.1 + 0.9 * match_rate
            raw_weights[cat] = weight
            total_weight_sum += weight

        # Normalize weights
        normalized_weights = {cat: w / total_weight_sum for cat, w in raw_weights.items()}

        # Compute adjusted overall score
        adjusted_score = 0.0
        for cat in categories:
            adjusted_score += normalized_weights[cat] * sub_scores.get(cat, 80)

        adjusted_score = int(round(adjusted_score))

        # Clamp score between 0 and 100
        adjusted_score = max(0, min(100, adjusted_score))

        # Adjust recommendation based on score
        if adjusted_score >= 80:
            adjusted_reco = "GO"
        elif adjusted_score >= 50:
            adjusted_reco = "CONDITIONAL"
        else:
            adjusted_reco = "NO-GO"

        logger.info(f"Adjusted score for org {org_id}: {adjusted_score} (originally {default_score}) based on {total_decisions} decisions.")
        return adjusted_score, adjusted_reco

    except Exception as e:
        logger.error(f"Error calibrating score: {str(e)}", exc_info=True)
        return default_score, default_reco


@celery_app.task(name="vcdiligence.tasks.run_due_diligence_task")
def run_due_diligence_task(domain: str, url: str, org_id: int, user_id: int, user_email: str):
    """
    Runs the multi-agent crew as a Celery task, updating DB Task rows.
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
        parsed_score, parsed_recommendation, sub_scores = parse_report_meta(markdown_report)

        # Apply Bloque B.2 adjusted weights calibration if decisions exist
        score, recommendation = get_adjusted_score_for_org(db, org_id, sub_scores, parsed_score, parsed_recommendation)

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
