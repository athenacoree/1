import os
import re
import json
import httpx
import asyncio
import threading
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from vcdiligence.scraper import SmartScraper
from vcdiligence.llm_manager import LLMProviderManager
from vcdiligence.crew import MarketResearchCrew

app = FastAPI(title="VCDueDiligenceAgent")

TASKS = {}

class AnalyzeRequest(BaseModel):
    url: str

def parse_report_meta(markdown_text):
    score_match = re.search(r"INVESTMENT_SCORE:\s*(\d+)", markdown_text, re.IGNORECASE)
    recommendation_match = re.search(r"RECOMMENDATION:\s*([A-Z\-]+)", markdown_text, re.IGNORECASE)
    score = int(score_match.group(1)) if score_match else 85
    recommendation = recommendation_match.group(1).strip() if recommendation_match else "GO"
    return score, recommendation

def run_due_diligence(domain, url):
    try:
        TASKS[domain] = {"status": "scraping", "progress": 15, "message": "Scraping startup web presence..."}
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

        TASKS[domain] = {"status": "analyzing", "progress": 40, "message": "Coordinating CrewAI multi-agent market & product analysis..."}

        crew_obj = MarketResearchCrew()
        inputs = {
            "company_name": payload.get("company_name", "Startup"),
            "company_url": payload.get("company_url", url),
            "homepage_summary": payload.get("homepage_summary", "")[:2500],
            "internal_pages_text": internal_pages_text[:2500],
            "competitor_insights": competitors[:2500],
            "pricing_and_product_insights": pricing_product[:2500],
            "market_and_funding_insights": market_funding[:2500],
            "team_and_founders_insights": team_founders[:2500]
        }

        result_output = crew_obj.crew().kickoff(inputs=inputs)
        markdown_report = getattr(result_output, "raw", str(result_output))
        score, recommendation = parse_report_meta(markdown_report)

        report_path = os.path.join("vcdiligence", "reports", f"{domain}.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(markdown_report)

        final_data = {
            "company_name": payload.get("company_name"),
            "company_url": url,
            "score": score,
            "recommendation": recommendation,
            "report_md": markdown_report,
            "llm_provider": crew_obj.provider_name
        }

        result_cache_path = os.path.join("vcdiligence", "cache", f"result_{domain}.json")
        with open(result_cache_path, "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)

        TASKS[domain] = {
            "status": "completed",
            "progress": 100,
            "message": "Analysis successfully completed!",
            "result": final_data
        }
    except Exception as e:
        TASKS[domain] = {
            "status": "failed",
            "progress": 0,
            "message": f"Analysis failed: {str(e)}"
        }

async def keep_alive_ping():
    await asyncio.sleep(15)
    async with httpx.AsyncClient() as client:
        while True:
            try:
                port = os.getenv("PORT", "10000")
                await client.get(f"http://127.0.0.1:{port}/health")
            except Exception:
                pass
            await asyncio.sleep(600)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(keep_alive_ping())

@app.get("/health")
def health_check():
    provider_llm, provider_name = LLMProviderManager.get_llm()
    return {"status": "ok", "provider": provider_name}

@app.post("/analyze")
def start_analysis(request: AnalyzeRequest, background_tasks: BackgroundTasks):
    url = request.url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    domain = SmartScraper.get_domain(url)

    result_cache_path = os.path.join("vcdiligence", "cache", f"result_{domain}.json")
    if os.path.exists(result_cache_path):
        try:
            with open(result_cache_path, "r", encoding="utf-8") as f:
                cached_result = json.load(f)
            TASKS[domain] = {
                "status": "completed",
                "progress": 100,
                "message": "Loaded cached investment analysis successfully.",
                "result": cached_result
            }
            return {"status": "completed", "task_id": domain}
        except Exception:
            pass

    if domain in TASKS and TASKS[domain]["status"] in ["scraping", "analyzing"]:
        return {"status": "running", "task_id": domain}

    TASKS[domain] = {"status": "starting", "progress": 5, "message": "Starting due diligence agent network..."}

    thread = threading.Thread(target=run_due_diligence, args=(domain, url))
    thread.start()

    return {"status": "running", "task_id": domain}

@app.get("/status/{task_id}")
def get_status(task_id: str):
    if task_id not in TASKS:
        result_cache_path = os.path.join("vcdiligence", "cache", f"result_{task_id}.json")
        if os.path.exists(result_cache_path):
            try:
                with open(result_cache_path, "r", encoding="utf-8") as f:
                    cached_result = json.load(f)
                return {
                    "status": "completed",
                    "progress": 100,
                    "message": "Loaded cached investment analysis.",
                    "result": cached_result
                }
            except Exception:
                pass
        raise HTTPException(status_code=404, detail="Task not found")

    return TASKS[task_id]

@app.get("/")
def get_index():
    index_path = os.path.join("vcdiligence", "templates", "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Frontend template not found")
    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

def main():
    import uvicorn
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run("vcdiligence.app:app", host="0.0.0.0", port=port, reload=True)

if __name__ == "__main__":
    main()
