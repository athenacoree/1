import re
import json
from vcdiligence.logging_config import logger

def parse_report_meta(markdown_text: str):
    """
    Parses metadata from the generated markdown report.
    Looks for:
    - INVESTMENT_SCORE: XX
    - RECOMMENDATION: YY
    - SUB_SCORES: { ... }
    """
    score_match = re.search(r"INVESTMENT_SCORE:\s*(\d+)", markdown_text, re.IGNORECASE)
    recommendation_match = re.search(r"RECOMMENDATION:\s*([A-Z\-]+)", markdown_text, re.IGNORECASE)

    score = int(score_match.group(1)) if score_match else 85
    recommendation = recommendation_match.group(1).strip() if recommendation_match else "GO"

    # Defaults
    sub_scores = {
        "market": 80,
        "team": 80,
        "product": 80,
        "traction": 80,
        "risk_legal_omissions": 80
    }

    sub_match = re.search(r"SUB_SCORES:\s*(\{.*?\})", markdown_text, re.IGNORECASE | re.DOTALL)
    if sub_match:
        try:
            parsed_json = json.loads(sub_match.group(1).strip())
            # Map standard keys
            for key in ["market", "team", "product", "traction", "risk_legal_omissions"]:
                if key in parsed_json:
                    sub_scores[key] = int(parsed_json[key])
        except Exception as e:
            logger.warning(f"Failed to parse sub_scores json block: {str(e)}")

    # Fallback to look for raw text sub-scores if JSON not found
    else:
        for key in ["market", "team", "product", "traction", "risk_legal_omissions"]:
            pattern = rf"{key}\s*:\s*(\d+)"
            m = re.search(pattern, markdown_text, re.IGNORECASE)
            if m:
                sub_scores[key] = int(m.group(1))

    return score, recommendation, sub_scores
