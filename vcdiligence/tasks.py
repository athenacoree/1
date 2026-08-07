import os
import json
from vcdiligence.database import SessionLocal, Organization, Report, Task, UserWallet
from vcdiligence.logging_config import logger
from vcdiligence.scraper import SmartScraper
from vcdiligence.parser import parse_report_meta, merge_devils_advocate
from vcdiligence.public_apis import get_all_public_insights
from vcdiligence.source_orchestrator import run_orchestrated_analysis, search_founders_and_team
from vcdiligence.pdf_generator import generate_report_pdf
from vcdiligence.crew import MarketResearchCrew, run_crew_with_rotation
from vcdiligence.security import create_access_token
from vcdiligence.monitoring import send_report_ready_email

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


def run_due_diligence_task(
    domain: str,
    url: str,
    org_id: int,
    user_id: int,
    user_email: str,
    extra_context: dict = None,
    notify_email: str = None,
    user_enabled_sources: list = None,
    user_priorities: list = None,
    custom_focus_keywords: str = None,
    language: str = "es",
    force_refresh: bool = False,
    credit_charged: bool = False,
    validated_ip: str = None
):
    """
    Runs the multi-agent crew as a background task, updating DB Task rows.
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

        # Scrape company landing and internal pages first (needed for heuristics)
        payload = SmartScraper.analyze_startup(url, validated_ip=validated_ip)

        # Build list of scanned pages and update progress message in real-time
        internal_keys = [k for k in payload.get("internal_pages", {}).keys() if "-missing-page" not in k]
        domain_name = SmartScraper.get_domain(url)
        pages_scanned = [domain_name] + [domain_name + k for k in internal_keys]
        scraped_formatted_str = ", ".join(pages_scanned)

        task = db.query(Task).filter_by(id=f"{org_id}_{domain}").first()
        if task:
            task.message = f"Se consultaron estas páginas: {scraped_formatted_str}"
            db.commit()

        internal_pages_text = ""
        for path, content in payload.get("internal_pages", {}).items():
            internal_pages_text += f"\n--- Page: {path} ---\n{content}\n"
        if not internal_pages_text:
            internal_pages_text = "No internal pages found."

        scraped_text = payload.get("homepage_summary", "") + "\n" + internal_pages_text

        # Gather public API insights via orchestrator
        company_name = domain.split('.')[0].capitalize()
        logger.info(f"Running Orchestrated Public API queries for {company_name}")
        public_insights = run_orchestrated_analysis(
            company_name=company_name,
            domain=domain,
            scraped_text=scraped_text,
            user_enabled_sources=user_enabled_sources,
            force_refresh=force_refresh
        )
        public_insights_text = json.dumps(public_insights, indent=2)

        competitors = json.dumps(payload.get("search_insights", {}).get("competitors", []), indent=2)
        pricing_product = json.dumps(payload.get("search_insights", {}).get("pricing_and_product", []), indent=2)
        market_funding = json.dumps(payload.get("search_insights", {}).get("market_and_funding", []), indent=2)

        # Real Founders & Executive Team Research
        team_list = search_founders_and_team(
            company_name=company_name,
            scraped_text=scraped_text,
            search_results=payload.get("search_insights", {}).get("team_and_founders", [])
        )

        team_structured_str = ""
        if team_list:
            team_structured_str = "EQUIPO EJECUTIVO Y FUNDADORES ENCONTRADOS (LISTADO REAL CON ENLACES):\n"
            for p in team_list:
                linkedin_str = p['linkedin_url'] if p['linkedin_url'] else "No disponible"
                team_structured_str += f"- Nombre: {p['name']}, Cargo: {p['role']}, LinkedIn: {linkedin_str}\n"
        else:
            team_structured_str = "No se encontraron detalles estructurados de fundadores/ejecutivos directamente en la búsqueda. Por favor busca en los datos crudos.\n"

        team_founders = team_structured_str + "\nRaw Team and Founders search records:\n" + json.dumps(payload.get("search_insights", {}).get("team_and_founders", []), indent=2)

        # Append LinkedIn context to team founders insights if present
        if extra_context and "linkedin_data" in extra_context:
            team_founders += f"\n\nAdditional LinkedIn Context:\n{extra_context['linkedin_data']}"

        # Append Pitch Deck text to homepage summary if present
        homepage_summary_text = payload.get("homepage_summary", "")
        if extra_context and "pitch_deck_text" in extra_context:
            homepage_summary_text += f"\n\nPitch Deck Extracted Context:\n{extra_context['pitch_deck_text']}"

        # 2. Update status to analyzing
        task = db.query(Task).filter_by(id=f"{org_id}_{domain}").first()
        if task:
            task.status = "analyzing"
            task.progress = 40
            task.message = "Coordinating CrewAI multi-agent market, product & omission analysis..."
            db.commit()

        def task_callback(task_output):
            db_cb = SessionLocal()
            try:
                t = db_cb.query(Task).filter_by(id=f"{org_id}_{domain}").first()
                if t:
                    t.status = "debating"
                    t.progress = 75
                    t.message = "Cuestionando la recomendación: buscando el mejor contraargumento..."
                    db_cb.commit()
            except Exception as e:
                logger.error(f"Error in task status callback: {str(e)}")
            finally:
                db_cb.close()

        output_language = "Spanish" if language == "es" else "English"
        inputs = {
            "company_name": payload.get("company_name", company_name),
            "company_url": payload.get("company_url", url),
            "homepage_summary": homepage_summary_text[:2500],
            "internal_pages_text": internal_pages_text[:2500],
            "competitor_insights": competitors[:2500],
            "pricing_and_product_insights": pricing_product[:2500],
            "market_and_funding_insights": market_funding[:2500],
            "team_and_founders_insights": team_founders[:2500],
            "public_api_insights": public_insights_text[:3500],
            "scraped_pages_list": "Páginas scrapeadas: " + scraped_formatted_str,
            "output_language": output_language
        }

        # Run CrewAI kickoff with automatic rotation
        result_output, provider_name = run_crew_with_rotation(
            inputs=inputs,
            task_callback=task_callback,
            user_priorities=user_priorities,
            custom_focus_keywords=custom_focus_keywords,
            db_session=db,
            task_id=f"{org_id}_{domain}"
        )

        # Merge business analyst memo and devils advocate section
        try:
            tasks_out = getattr(result_output, "tasks_output", [])
            if len(tasks_out) >= 7:
                business_analyst_report = tasks_out[5].raw
                devils_advocate_section = tasks_out[6].raw
                markdown_report = merge_devils_advocate(business_analyst_report, devils_advocate_section)
            else:
                markdown_report = getattr(result_output, "raw", str(result_output))
        except Exception as e:
            logger.error(f"Error merging Devil's Advocate section: {str(e)}")
            markdown_report = getattr(result_output, "raw", str(result_output))

        # Parse metadata
        parsed_score, parsed_recommendation, sub_scores = parse_report_meta(markdown_report)

        # Apply Bloque B.2 adjusted weights calibration if decisions exist
        score, recommendation = get_adjusted_score_for_org(db, org_id, sub_scores, parsed_score, parsed_recommendation)

        # Extract specialist sources for screenshot candidates
        specialist_urls = []
        try:
            tasks_out = getattr(result_output, "tasks_output", [])
            for i in range(5):
                if i < len(tasks_out):
                    pydantic_res = getattr(tasks_out[i], "pydantic", None)
                    if pydantic_res and hasattr(pydantic_res, "sources") and pydantic_res.sources:
                        for src in pydantic_res.sources:
                            if src.url:
                                specialist_urls.append((src.url, src.name))
        except Exception as e:
            logger.error(f"Error extracting specialist sources: {str(e)}")

        # Collect exactly 4 screenshots from different relevant sources
        screenshots_to_capture = []
        captured_set = set()

        # 1. Company official website
        if url:
            screenshots_to_capture.append({"url": url, "name": "Sitio Oficial"})
            captured_set.add(url.lower())

        # 2. Market/Funding source
        market_url = None
        market_name = "Información de Mercado"
        for r in payload.get("search_insights", {}).get("market_and_funding", []):
            lnk = r.get("link")
            if lnk and lnk.lower() not in captured_set:
                market_url = lnk
                if "crunchbase.com" in lnk:
                    market_name = "Crunchbase Profile"
                break
        if market_url:
            screenshots_to_capture.append({"url": market_url, "name": market_name})
            captured_set.add(market_url.lower())

        # 3. Company LinkedIn / Social profile
        linkedin_url = None
        for r in payload.get("search_insights", {}).get("team_and_founders", []):
            lnk = r.get("link")
            if lnk and "linkedin.com" in lnk.lower() and lnk.lower() not in captured_set:
                linkedin_url = lnk
                break
        if not linkedin_url:
            for r in payload.get("search_insights", {}).get("competitors", []):
                lnk = r.get("link")
                if lnk and lnk.lower() not in captured_set:
                    linkedin_url = lnk
                    break
        if linkedin_url:
            screenshots_to_capture.append({"url": linkedin_url, "name": "LinkedIn / Social"})
            captured_set.add(linkedin_url.lower())

        # 4. Specialist-cited source
        spec_url = None
        spec_name = "Fuente Citada"
        for s_url, s_name in specialist_urls:
            if s_url and s_url.lower() not in captured_set:
                spec_url = s_url
                spec_name = s_name
                break
        if not spec_url:
            for r in payload.get("search_insights", {}).get("pricing_and_product", []):
                lnk = r.get("link")
                if lnk and lnk.lower() not in captured_set:
                    spec_url = lnk
                    spec_name = "Reseña / Producto"
                    break
        if spec_url:
            screenshots_to_capture.append({"url": spec_url, "name": spec_name})
            captured_set.add(spec_url.lower())

        # Fetch screenshots via service
        from vcdiligence.screenshot_service import capture_screenshot
        screenshot_gallery = []
        for s in screenshots_to_capture[:4]:
            img_url = capture_screenshot(s["url"], db_session=db)
            if img_url:
                screenshot_gallery.append({
                    "url": s["url"],
                    "name": s["name"],
                    "screenshot_url": img_url
                })

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
            "report_md": markdown_report,
            "screenshot_gallery": screenshot_gallery,
            "triggered_conditional_sources": public_insights.get("triggered_conditional_sources", [])
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
                llm_provider=provider_name,
                screenshot_gallery=screenshot_gallery,
                organization_id=org_id
            )
            db.add(report)
        else:
            report.score = score
            report.sub_scores = sub_scores
            report.recommendation = recommendation
            report.report_md = markdown_report
            report.pdf_path = pdf_path
            report.llm_provider = provider_name
            report.screenshot_gallery = screenshot_gallery
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
            "llm_provider": provider_name,
            "pdf_path": f"/reports/{domain}/pdf",
            "screenshot_gallery": screenshot_gallery,
            "created_at": datetime.datetime.utcnow().isoformat()
        }

        task = db.query(Task).filter_by(id=f"{org_id}_{domain}").first()
        if task:
            task.status = "completed"
            task.progress = 100
            task.message = "Analysis successfully completed!"
            task.result_json = final_data
            db.commit()

        # Send SMTP notification
        email_to = notify_email or user_email
        token = create_access_token(data={"sub": user_email})
        port = os.getenv("PORT", "10000")
        app_base_url = os.getenv("APP_BASE_URL")
        if not app_base_url:
            logger.warning("APP_BASE_URL environment variable is not set. Falling back to localhost.")
        base_url = (app_base_url or f"http://localhost:{port}").rstrip('/')
        pdf_url = f"{base_url}/reports/{domain}/pdf?token={token}"

        if email_to:
            try:
                send_report_ready_email(
                    to_email=email_to,
                    company_name=company_name,
                    score=score,
                    pdf_url=pdf_url
                )
            except Exception as mail_err:
                logger.error(f"Failed to send task ready email: {str(mail_err)}")

        # Check if WhatsApp delivery requested and notify the administrator
        if extra_context and "whatsapp_delivery" in extra_context:
            try:
                wa_details = extra_context["whatsapp_delivery"]
                wa_num = wa_details.get("whatsapp_number")
                user_mail = wa_details.get("user_email")

                wa_subject = f"📱 [WhatsApp Delivery Needed] Reporte de {company_name} listo"
                wa_body = (
                    f"Atención Administrador:\n\n"
                    f"El usuario {user_mail} ha solicitado recibir su reporte de due diligence por WhatsApp.\n\n"
                    f"Detalles de la entrega:\n"
                    f"- Empresa: {company_name}\n"
                    f"- Score: {score}/100\n"
                    f"- Número WhatsApp: {wa_num}\n"
                    f"- Enlace de descarga del Reporte PDF: {pdf_url}\n\n"
                    f"Por favor, reenvíe manualmente el archivo o el enlace al cliente."
                )
                from vcdiligence.monitoring import send_smtp_alert
                send_smtp_alert(wa_subject, wa_body)
                logger.info(f"Admin WhatsApp notice dispatched successfully for user {user_mail} and number {wa_num}")
            except Exception as wa_err:
                logger.error(f"Failed to dispatch WhatsApp manual delivery notice to admin: {str(wa_err)}")

    except Exception as e:
        logger.error(f"Error running due diligence background task: {str(e)}", exc_info=True)
        task = db.query(Task).filter_by(id=f"{org_id}_{domain}").first()
        if task:
            task.status = "failed"
            task.progress = 0
            task.message = f"Analysis failed: {str(e)}"
            db.commit()
        if credit_charged:
            try:
                wallet = db.query(UserWallet).filter_by(user_id=user_id).with_for_update().first()
                if wallet:
                    wallet.credits_balance += 1
                    db.commit()
                    logger.info(f"Refunded 1 credit to user {user_id} due to analysis failure. New balance: {wallet.credits_balance}")
            except Exception as refund_err:
                logger.error(f"Failed to refund credit to user {user_id}: {str(refund_err)}")
    finally:
        db.close()
