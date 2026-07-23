import os
import json
import datetime
import smtplib
from email.mime.text import MIMEText
import requests
from unittest import mock

from vcdiligence.database import SessionLocal, Report, ReportChange
from vcdiligence.logging_config import logger
from vcdiligence.public_apis import get_all_public_insights, PUBLIC_CACHE_DIR
from vcdiligence.scraper import SmartScraper
from vcdiligence.crew import MarketResearchCrew
from vcdiligence.parser import parse_report_meta
from vcdiligence.tasks import get_adjusted_score_for_org

def get_old_cached_insight(api_name: str, company_name: str) -> dict:
    """Reads old cached insight from disk if it exists."""
    safe_query = "".join([c if c.isalnum() else "_" for c in company_name])
    cache_path = os.path.join(PUBLIC_CACHE_DIR, f"{api_name}_{safe_query}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
                return cached.get("data")
        except Exception:
            pass
    return None

def send_smtp_alert(subject: str, body: str):
    """Sends email alert via SMTP if configured in environment."""
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT", "587")
    smtp_user = os.getenv("SMTP_USERNAME")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", "noreply@dealscout.ai")

    if not smtp_host or not smtp_user or not smtp_pass:
        logger.info("SMTP alert skipped: connection details not configured.")
        return

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = smtp_from
        msg["To"] = smtp_user  # Send to the configured user email

        server = smtplib.SMTP(smtp_host, int(smtp_port))
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_from, [smtp_user], msg.as_string())
        server.close()
        logger.info(f"SMTP notification sent successfully for subject: {subject}")
    except Exception as e:
        logger.error(f"Failed to send SMTP email notification: {str(e)}", exc_info=True)

def send_slack_alert(text: str):
    """Sends Slack webhook notification if configured in environment."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.info("Slack notification skipped: SLACK_WEBHOOK_URL not configured.")
        return

    try:
        payload = {"text": text}
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("Slack notification sent successfully.")
        else:
            logger.error(f"Slack webhook returned status code {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {str(e)}", exc_info=True)

def run_continuous_monitoring_job():
    """
    Schedules job to iterate through existing active reports, rerun scrapers + public APIs,
    detect changes, log them, and notify users.
    """
    logger.info("Starting scheduled continuous monitoring job.")
    db = SessionLocal()
    try:
        reports = db.query(Report).filter_by(monitoring_enabled=True).all()
        logger.info(f"Found {len(reports)} reports configured for active monitoring.")

        for r in reports:
            # Check frequency window
            now = datetime.datetime.utcnow()
            last_checked = r.last_monitored_at or r.created_at
            elapsed_days = (now - last_checked).total_seconds() / 86400.0
            if elapsed_days < r.monitoring_interval_days:
                logger.info(f"Skipping report for {r.domain}: only {elapsed_days:.2f} days elapsed out of {r.monitoring_interval_days} interval.")
                continue

            logger.info(f"Monitoring report for {r.domain} (interval: {r.monitoring_interval_days} days).")
            company_name = r.domain.split('.')[0].capitalize()

            # 1. Fetch old cached insights from disk
            old_sec = get_old_cached_insight("sec_edgar", company_name)
            old_court = get_old_cached_insight("courtlistener", company_name)
            old_github = get_old_cached_insight("github", company_name)

            # 2. Force fresh fetch of live public insights (bypassing cache by mocking get_cached_response)
            with mock.patch("vcdiligence.public_apis.get_cached_response", return_value=None):
                new_sec = get_all_public_insights(company_name)

            # 3. Compare public insights
            detected_changes = []

            # SEC Edgar comparison
            if new_sec:
                new_sec_data = new_sec.get("sec_edgar", {})
                old_filings = (old_sec or {}).get("recent_filings", []) if old_sec else []
                new_filings = new_sec_data.get("recent_filings", []) if new_sec_data else []
                if len(new_filings) > len(old_filings):
                    desc = f"New SEC filings detected! Count went from {len(old_filings)} to {len(new_filings)}."
                    detected_changes.append(("sec_edgar", desc, json.dumps(old_filings), json.dumps(new_filings)))
                elif new_filings != old_filings:
                    desc = "SEC filings updated."
                    detected_changes.append(("sec_edgar", desc, json.dumps(old_filings), json.dumps(new_filings)))

            # CourtListener comparison
            if new_sec:
                new_court_data = new_sec.get("courtlistener", {})
                old_cases = (old_court or {}).get("cases", []) if old_court else []
                new_cases = new_court_data.get("cases", []) if new_court_data else []
                if len(new_cases) > len(old_cases):
                    desc = f"New potential litigation records detected on CourtListener! Count went from {len(old_cases)} to {len(new_cases)}."
                    detected_changes.append(("courtlistener", desc, json.dumps(old_cases), json.dumps(new_cases)))

            # GitHub comparison
            if new_sec:
                new_github_data = new_sec.get("github", {})
                old_repos = (old_github or {}).get("repositories", []) if old_github else []
                new_repos = new_github_data.get("repositories", []) if new_github_data else []
                if len(new_repos) != len(old_repos):
                    desc = f"GitHub repositories count changed from {len(old_repos)} to {len(new_repos)}."
                    detected_changes.append(("github", desc, json.dumps(old_repos), json.dumps(new_repos)))
                else:
                    # check for star count change
                    for nr in new_repos:
                        for or_ in old_repos:
                            if nr["name"] == or_["name"] and nr["stars"] != or_["stars"]:
                                desc = f"GitHub repository {nr['name']} star count changed from {or_['stars']} to {nr['stars']}."
                                detected_changes.append(("github", desc, str(or_["stars"]), str(nr["stars"])))
                                break

            # 4. Recalculate score (run crew to get fresh score/reco)
            try:
                # Scrape company landing and internal pages
                payload = SmartScraper.analyze_startup(r.url)
                internal_pages_text = ""
                for path, content in payload.get("internal_pages", {}).items():
                    internal_pages_text += f"\n--- Page: {path} ---\n{content}\n"

                competitors = json.dumps(payload.get("search_insights", {}).get("competitors", []), indent=2)
                pricing_product = json.dumps(payload.get("search_insights", {}).get("pricing_and_product", []), indent=2)
                market_funding = json.dumps(payload.get("search_insights", {}).get("market_and_funding", []), indent=2)
                team_founders = json.dumps(payload.get("search_insights", {}).get("team_and_founders", []), indent=2)

                crew_obj = MarketResearchCrew()
                inputs = {
                    "company_name": payload.get("company_name", company_name),
                    "company_url": payload.get("company_url", r.url),
                    "homepage_summary": payload.get("homepage_summary", "")[:2500],
                    "internal_pages_text": internal_pages_text[:2500],
                    "competitor_insights": competitors[:2500],
                    "pricing_and_product_insights": pricing_product[:2500],
                    "market_and_funding_insights": market_funding[:2500],
                    "team_and_founders_insights": team_founders[:2500],
                    "public_api_insights": json.dumps(new_sec, indent=2)[:3500]
                }

                result_output = crew_obj.crew().kickoff(inputs=inputs)
                markdown_report = getattr(result_output, "raw", str(result_output))

                parsed_score, parsed_recommendation, sub_scores = parse_report_meta(markdown_report)

                # Calibrate score using organization decisions weights
                new_score, new_reco = get_adjusted_score_for_org(db, r.organization_id, sub_scores, parsed_score, parsed_recommendation)

                # Check if score changed
                if new_score != r.score or new_reco != r.recommendation:
                    desc = f"Overall Investment Score changed from {r.score} ({r.recommendation}) to {new_score} ({new_reco})."
                    detected_changes.append(("score_change", desc, f"{r.score} ({r.recommendation})", f"{new_score} ({new_reco})"))

                    # Update report
                    r.score = new_score
                    r.recommendation = new_reco
                    r.sub_scores = sub_scores
                    r.report_md = markdown_report
                    # Regenerate PDF path will happen on-the-fly when requested or updated
                    r.pdf_path = None
                    db.commit()

            except Exception as e:
                logger.error(f"Error recalculating score during monitoring for {r.domain}: {str(e)}", exc_info=True)

            # 5. Log changes to database & trigger notifications
            if detected_changes:
                for change_type, change_desc, old_val, new_val in detected_changes:
                    change_log = ReportChange(
                        report_id=r.id,
                        change_type=change_type,
                        description=change_desc,
                        old_value=old_val,
                        new_value=new_val
                    )
                    db.add(change_log)
                db.commit()

                # Build consolidated alert message
                notification_msg = f"🚨 *[DealScout AI] Alerta de Monitoreo para {company_name}* ({r.domain}):\n\n"
                for _, change_desc, _, _ in detected_changes:
                    notification_msg += f"- {change_desc}\n"
                notification_msg += f"\nVer detalles en tu panel de control."

                # Send Slack notification
                send_slack_alert(notification_msg)

                # Send email notification
                email_subject = f"[DealScout AI] Alerta de Cambio Detectado: {company_name}"
                send_smtp_alert(email_subject, notification_msg)

            # Update last monitored timestamp
            r.last_monitored_at = datetime.datetime.utcnow()
            db.commit()

    except Exception as e:
        logger.error(f"Error running continuous monitoring job: {str(e)}", exc_info=True)
    finally:
        db.close()
