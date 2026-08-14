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


def generate_hype_and_qa(scraped_text: str, company_name: str, db_session=None) -> dict:
    """
    Analyzes website text or pitch deck text to perform a 'Hype Audit'
    (detecting standard overused startup clichés and calculating a Hype Score)
    and simulates 3-5 hard-hitting Investment Committee Q&As.
    """
    # Predefined buzzwords list for safe local extraction / fallback
    buzzwords = {
        "disrupt": "Afirma 'disrumpir' el mercado, un término sobreutilizado para evasión de competencia real.",
        "revolutionary": "Califica su solución de 'revolucionaria' sin antes haber validado el product-market fit.",
        "next-gen": "Usa 'próxima generación' para sonar futurista, pero suele encubrir tecnología estándar.",
        "paradigm shift": "Menciona un 'cambio de paradigma', lo cual es sumamente raro en etapas tempranas.",
        "ai-powered": "Se autodenomina 'potenciado por IA', un cliché clásico para atraer capital sin detallar su modelo.",
        "cutting-edge": "Usa 'tecnología de punta', un adjetivo vacío que no aporta detalles de arquitectura real.",
        "game-changer": "Se vende como un 'punto de inflexión' o cambiador de reglas de juego de forma prematura.",
        "world-class": "Presume de un equipo o producto 'de clase mundial' sin métricas internacionales comprobables.",
        "uber for": "Utiliza la analogía 'el Uber de ...', demostrando falta de originalidad en el modelo de negocio.",
        "pioneering": "Se autoproclama 'pionero' ignorando soluciones consolidadas en el mercado."
    }

    detected = []
    text_lower = scraped_text.lower() if scraped_text else ""
    total_count = 0

    for word, desc in buzzwords.items():
        # Match word prefix or substring to handle adjectives/plurals robustly (e.g. disrupt matching disruptive)
        matches = len(re.findall(re.escape(word), text_lower))
        if matches > 0:
            total_count += matches
            severity = "low"
            if matches >= 3:
                severity = "high"
            elif matches >= 2:
                severity = "medium"

            detected.append({
                "word": word.title() if word != "ai-powered" else "AI-Powered",
                "count": matches,
                "severity": severity,
                "explanation": desc
            })

    # Calculate baseline hype score
    # 0 to 100 based on cliché frequency and density
    hype_score = min(100, int(total_count * 8))
    # Minimum score if nothing detected
    if hype_score == 0:
        hype_score = 15 # baseline optimism

    # Default simulated Q&As (Fallback)
    simulated_questions = [
        {
            "question": f"¿Cómo planea {company_name} defenderse frente a competidores establecidos si su propuesta de valor se basa principalmente en adjetivos promocionales?",
            "answer": "El inversor debe presionar para ver barreras de entrada reales (moats), contratos firmados o patentes, en lugar de confiar en la narrativa comercial."
        },
        {
            "question": f"Dado el uso de terminología como IA o innovación en su sitio, ¿cuál es el porcentaje real de automatización frente al trabajo manual detrás de escena?",
            "answer": "Se debe solicitar una demo técnica en vivo o auditar la base de código en GitHub para validar que no sea 'IA con humanos detrás'."
        },
        {
            "question": f"¿Cuál es el costo de adquisición de clientes (CAC) real y cómo se compara con el valor de vida del cliente (LTV)?",
            "answer": "El comité de inversión debe exigir las métricas unitarias financieras detalladas y el desglose de cohortes para comprobar la viabilidad del negocio a largo plazo."
        }
    ]

    result = {
        "hype_score": hype_score,
        "detected_cliches": detected,
        "simulated_questions": simulated_questions
    }

    # Now let's try to enrich via LLM if available
    try:
        from vcdiligence.llm_manager import LLMProviderManager
        llm, provider_name, key_id = LLMProviderManager.get_llm_from_pool(db_session=db_session)
        if llm and getattr(llm, "api_key", None) and not getattr(llm, "api_key", "").startswith("mock"):
            import litellm
            # Build prompt
            prompt = f"""
            Analiza el texto de la startup '{company_name}' para realizar una auditoría de Hype/Humo y simular una sesión de preguntas difíciles del Comité de Inversión.
            Texto extraído del sitio web/pitch deck:
            \"\"\"
            {scraped_text[:2000]}
            \"\"\"

            Responde ÚNICAMENTE con un objeto JSON válido en español con la siguiente estructura exacta:
            {{
              "hype_score": <int entre 0 y 100 indicando el nivel de humo o marketing exagerado del texto>,
              "detected_cliches": [
                {{
                  "word": "<palabra clave o frase trillada detectada>",
                  "count": <número de ocurrencias estimadas>,
                  "severity": "<low, medium o high>",
                  "explanation": "<explicación humorística pero muy profesional de por qué es un cliché y qué oculta>"
                }}
              ],
              "simulated_questions": [
                {{
                  "question": "<pregunta incómoda y sumamente difícil que el Comité de Inversión de VC debería hacerle a los fundadores basado en las debilidades o lagunas de su texto>",
                  "answer": "<consejo o recomendación para el analista de VC sobre qué respuesta exigir o cómo auditar esa respuesta>"
                }}
              ]
            }}
            """

            response = litellm.completion(
                model=llm.model,
                api_key=llm.api_key,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                timeout=15
            )
            content = response.choices[0].message.content.strip()
            # Parse JSON safely
            # Clean possible markdown block markers
            content_clean = re.sub(r"^```json\s*", "", content, flags=re.IGNORECASE)
            content_clean = re.sub(r"\s*```$", "", content_clean, flags=re.IGNORECASE).strip()

            parsed = json.loads(content_clean)
            if isinstance(parsed, dict) and "hype_score" in parsed:
                # Ensure structure is valid and merge
                result["hype_score"] = int(parsed.get("hype_score", hype_score))
                if parsed.get("detected_cliches"):
                    result["detected_cliches"] = parsed["detected_cliches"]
                if parsed.get("simulated_questions"):
                    result["simulated_questions"] = parsed["simulated_questions"]
                logger.info(f"Successfully generated Hype & QA Audit using LLM ({provider_name}) for {company_name}")
    except Exception as e:
        logger.warning(f"Could not use LLM for Hype & QA Audit, using rule-based generator: {str(e)}")

    return result
