from pydantic import BaseModel
from typing import List

class AgentFinding(BaseModel):
    category: str  # ej "market", "competition", "customer", "product", "omissions"
    score: int     # 0-100
    key_points: List[str]  # 3-6 bullets cortos, no parrafos
    red_flags: List[str]   # vacío si no hay nada preocupante
    is_clean: bool  # True si no hay hallazgos relevantes que destacar
