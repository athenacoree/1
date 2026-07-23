import os
import sys
import json
import argparse
from sqlalchemy.orm import Session

# Local imports
from vcdiligence.database import SessionLocal, init_db, PrecisionBenchmark
from vcdiligence.scraper import SmartScraper
from vcdiligence.public_apis import get_all_public_insights
from vcdiligence.crew import MarketResearchCrew
from vcdiligence.parser import parse_report_meta
from vcdiligence.logging_config import logger

def run_benchmark_startup(db: Session, name: str, url: str, known_outcome: str):
    """
    Runs full analysis on a known startup and logs benchmark results.
    """
    logger.info(f"Starting benchmark run for startup: {name} ({url})")
    try:
        domain = SmartScraper.get_domain(url)
        company_name = name

        # Fetch insights & scrape
        public_insights = get_all_public_insights(company_name)
        public_insights_text = json.dumps(public_insights, indent=2)

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

        # Run CrewAI agents
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
            "public_api_insights": public_insights_text[:3500]
        }

        result_output = crew_obj.crew().kickoff(inputs=inputs)
        markdown_report = getattr(result_output, "raw", str(result_output))

        # Parse score & recommendation
        score, recommendation, _ = parse_report_meta(markdown_report)

        # Determine if matched
        matched = False
        if known_outcome == "success" and recommendation == "GO":
            matched = True
        elif known_outcome == "failure" and recommendation == "NO-GO":
            matched = True
        elif known_outcome == "acquisition" and recommendation in ["GO", "CONDITIONAL"]:
            matched = True

        # Upsert in benchmark table
        bench = db.query(PrecisionBenchmark).filter_by(startup_name=name).first()
        if not bench:
            bench = PrecisionBenchmark(
                startup_name=name,
                url=url,
                score=score,
                recommendation=recommendation,
                known_outcome=known_outcome,
                matched=matched
            )
            db.add(bench)
        else:
            bench.url = url
            bench.score = score
            bench.recommendation = recommendation
            bench.known_outcome = known_outcome
            bench.matched = matched
        db.commit()

        logger.info(f"Successfully processed {name}: Score={score}, Recommendation={recommendation}, Matched={matched}")
        return bench

    except Exception as e:
        logger.error(f"Error benching startup {name}: {str(e)}", exc_info=True)
        return None

def main():
    parser = argparse.ArgumentParser(description="Run precision benchmarks for DealScout AI")
    parser.add_argument("--file", default="tests/test_benchmark_input.json", help="Path to JSON file containing startups")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    if not os.path.exists(args.file):
        print(f"Error: input file {args.file} not found.")
        # Let's write a default file to help the user if it doesn't exist
        default_data = [
            {"startup_name": "Stripe", "url": "https://stripe.com", "known_outcome": "success"},
            {"startup_name": "VC Diligence", "url": "https://vcdiligence.com", "known_outcome": "success"}
        ]
        os.makedirs(os.path.dirname(args.file) or ".", exist_ok=True)
        with open(args.file, "w") as f:
            json.dump(default_data, f, indent=2)
        print(f"Created default input file at {args.file}")

    with open(args.file, "r") as f:
        startups = json.load(f)

    print(f"Loaded {len(startups)} startups for benchmarking.")
    results = []
    for s in startups:
        bench_result = run_benchmark_startup(db, s["startup_name"], s["url"], s["known_outcome"])
        if bench_result:
            results.append(bench_result)

    print("\n" + "="*50)
    print("BENCHMARK RUN SUMMARY")
    print("="*50)
    matches_count = 0
    for r in results:
        match_str = "YES" if r.matched else "NO"
        if r.matched:
            matches_count += 1
        print(f"Startup: {r.startup_name} | Score: {r.score} | Reco: {r.recommendation} | Actual: {r.known_outcome} | Match: {match_str}")

    total = len(results)
    accuracy = (matches_count / total * 100.0) if total > 0 else 0.0
    print("-"*50)
    print(f"Total processed: {total} | Matched: {matches_count} | Accuracy: {accuracy:.2f}%")
    print("="*50)

    db.close()

if __name__ == "__main__":
    main()
