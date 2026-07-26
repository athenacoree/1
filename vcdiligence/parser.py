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


def merge_devils_advocate(business_report: str, devils_section: str) -> str:
    """
    Inserts the Devil's Advocate section into the business analyst's report.
    It should appear right after the top metadata lines (INVESTMENT_SCORE,
    RECOMMENDATION, SUB_SCORES) and before the rest of the details (Executive Summary, etc.).
    """
    if not business_report:
        return devils_section or ""

    lines = business_report.split("\n")
    meta_indices = []
    for idx, line in enumerate(lines):
        if any(prefix in line for prefix in ["INVESTMENT_SCORE:", "RECOMMENDATION:", "SUB_SCORES:"]):
            meta_indices.append(idx)

    insert_idx = max(meta_indices) + 1 if meta_indices else 0

    section_title = "## Caso a Favor vs. Caso en Contra"
    # Clean up the devils_section's first heading if any, and structure nicely
    clean_section = devils_section.strip()
    if clean_section.startswith("#"):
        # Remove any leading title like "# Caso a Favor..." or "# Análisis Contradictorio" if generated
        clean_section = re.sub(r"^#+\s+.*", "", clean_section).strip()

    formatted_section = f"\n{section_title}\n\n{clean_section}\n"

    # Reassemble report
    new_lines = lines[:insert_idx] + [formatted_section] + lines[insert_idx:]
    return "\n".join(new_lines)
