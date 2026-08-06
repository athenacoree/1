import os
import re
import requests
from vcdiligence.logging_config import logger

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

def extract_executive_summary(report_md: str) -> str:
    if not report_md:
        return ""
    # Try to find a section starting with Executive Summary or Resumen Ejecutivo
    match = re.search(r'(?:Executive Summary|Resumen Ejecutivo)[\s\S]*?(?=\n(?:#|\d|\*|-))', report_md, re.IGNORECASE)
    if match:
        content = match.group(0).strip()
        content = re.sub(r'^(?:#+\s*)?(?:Executive Summary|Resumen Ejecutivo)\s*', '', content, flags=re.IGNORECASE).strip()
        if content:
            return content[:2000]
    # Fallback: return the first 1000 characters of the report
    return report_md[:1000].strip()

def send_to_notion(report_data: dict) -> bool:
    """
    Sends report data to Notion database securely.
    Handles omission/config errors gracefully without throwing exceptions.
    """
    api_key = os.getenv("NOTION_API_KEY") or NOTION_API_KEY
    db_id = os.getenv("NOTION_DATABASE_ID") or NOTION_DATABASE_ID

    if not api_key or not db_id:
        logger.warning("Notion integration is not configured. NOTION_API_KEY or NOTION_DATABASE_ID missing.")
        return False

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    company_name = report_data.get("company_name", "Startup")
    score = report_data.get("score", 0)
    recommendation = report_data.get("recommendation", "CONDITIONAL")
    sub_scores = report_data.get("sub_scores", {})
    report_md = report_data.get("report_md", "")

    summary = extract_executive_summary(report_md)

    # Notion properties block (standard names)
    properties = {
        "Name": {
            "title": [
                {
                    "text": {
                        "content": company_name
                    }
                }
            ]
        },
        "Score": {
            "number": score
        },
        "Recommendation": {
            "select": {
                "name": recommendation
            }
        },
        "Market Score": {
            "number": sub_scores.get("market", 0)
        },
        "Team Score": {
            "number": sub_scores.get("team", 0)
        },
        "Product Score": {
            "number": sub_scores.get("product", 0)
        },
        "Traction Score": {
            "number": sub_scores.get("traction", 0)
        },
        "Risk Score": {
            "number": sub_scores.get("risk_legal_omissions", 0)
        }
    }

    children = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": "Resumen Ejecutivo / Executive Summary"
                        }
                    }
                ]
            }
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": summary or "No summary available."
                        }
                    }
                ]
            }
        }
    ]

    payload = {
        "parent": {
            "database_id": db_id
        },
        "properties": properties,
        "children": children
    }

    try:
        url = "https://api.notion.com/v1/pages"
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code in [200, 201]:
            logger.info(f"Successfully exported report for {company_name} to Notion.")
            return True
        else:
            logger.error(f"Notion API error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to connect to Notion API: {str(e)}")
        return False
