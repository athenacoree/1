import os
import json
import datetime
from vcdiligence.database import SessionLocal, init_db, Organization, User, Report, Task, UserWallet
from vcdiligence.security import hash_password

init_db()
db = SessionLocal()

# Ensure Org 1 and User exist
org = db.query(Organization).filter_by(id=1).first()
if not org:
    org = Organization(id=1, company_name="DealScout Capital")
    db.add(org)
    db.commit()

user = db.query(User).filter_by(email="analyst@dealscout.ai").first()
if not user:
    user = User(
        id=1,
        email="analyst@dealscout.ai",
        hashed_password=hash_password("analystpassword"),
        role="analista",
        organization_id=1
    )
    db.add(user)
    db.commit()
else:
    user.hashed_password = hash_password("analystpassword")
    db.commit()

# Ensure user wallet has credits
wallet = db.query(UserWallet).filter_by(user_id=user.id).first()
if not wallet:
    wallet = UserWallet(user_id=user.id, credits_balance=10)
    db.add(wallet)
    db.commit()

# Create Report & Task for test_hype.com with hype_qa populated
domain = "test_hype.com"
task_id = "1_test_hype.com"

hype_qa_data = {
    "hype_score": 68,
    "detected_cliches": [
        {
            "word": "AI-Powered",
            "count": 5,
            "severity": "high",
            "explanation": "Afirma estar 'potenciado por IA', un cliché clásico para llamar la atención de inversores sin especificar la tecnología real."
        },
        {
            "word": "Revolutionary",
            "count": 3,
            "severity": "medium",
            "explanation": "Califica su solución de 'revolucionaria' sin antes haber validado el product-market fit."
        },
        {
            "word": "Disruptive",
            "count": 2,
            "severity": "medium",
            "explanation": "Afirma 'disrumpir' el mercado, un término sobreutilizado para evasión de competencia real."
        }
    ],
    "simulated_questions": [
        {
            "question": "¿Cómo se diferencia la tecnología de IA de la empresa de las soluciones de código de código abierto existentes?",
            "answer": "El inversor debe presionar para ver el pipeline de datos propietario, ya que la mayoría de las startups son meras envolturas de APIs externas."
        },
        {
            "question": "Dado que se autoproclaman revolucionarios, ¿cuál es el porcentaje real de retención de cohortes a 6 meses?",
            "answer": "Exige ver el reporte de Stripe de retención y analíticas reales para validar si los clientes realmente encuentran valor a largo plazo."
        },
        {
            "question": "¿Cuál es su canal de adquisición orgánico principal para reducir el CAC?",
            "answer": "Valida si dependen enteramente de anuncios pagados de Meta/Google o si tienen canales orgánicos escalables."
        }
    ]
}

report = db.query(Report).filter_by(domain=domain, organization_id=1).first()
if report:
    db.delete(report)
    db.commit()

report = Report(
    domain=domain,
    company_name="Test Hype Inc",
    url="https://test_hype.com",
    score=82,
    sub_scores={"market": 85, "team": 80, "product": 82, "traction": 78, "risk_legal_omissions": 85},
    recommendation="GO",
    report_md="# Test Hype Memo\n\n## Summary\nThis is a highly-promoted AI startup.",
    hype_qa=hype_qa_data,
    organization_id=1
)
db.add(report)
db.commit()

task = db.query(Task).filter_by(id=task_id).first()
if task:
    db.delete(task)
    db.commit()

final_data = {
    "company_name": "Test Hype Inc",
    "domain": domain,
    "company_url": "https://test_hype.com",
    "score": 82,
    "recommendation": "GO",
    "sub_scores": {"market": 85, "team": 80, "product": 82, "traction": 78, "risk_legal_omissions": 85},
    "report_md": "# Test Hype Memo\n\n## Summary\nThis is a highly-promoted AI startup.",
    "llm_provider": "openai",
    "pdf_path": f"/reports/{domain}/pdf",
    "screenshot_gallery": [],
    "hype_qa": hype_qa_data,
    "created_at": datetime.datetime.utcnow().isoformat()
}

task = Task(
    id=task_id,
    domain=domain,
    status="completed",
    progress=100,
    message="Analysis successfully completed!",
    result_json=final_data,
    hype_qa=hype_qa_data,
    organization_id=1
)
db.add(task)
db.commit()

print("Successfully inserted demo report & task with Hype QA data!")
db.close()
