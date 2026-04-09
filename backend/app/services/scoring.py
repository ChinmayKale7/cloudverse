import json
import re
from typing import Optional

import requests


def compute_score(income: int, cgpa: float, category: str) -> float:
    """
    Simple, transparent scoring:
    - Higher CGPA increases score.
    - Lower income increases score.
    - Category adds a small bonus.
    """
    category_bonus = {
        "general": 0,
        "obc": 5,
        "sc": 10,
        "st": 12,
        "ews": 7,
    }

    normalized_category = category.strip().lower()
    bonus = category_bonus.get(normalized_category, 0)

    # Income component assumes annual income in same currency; tune as needed.
    income_component = max(0.0, 100.0 - (income / 1000.0))
    cgpa_component = min(10.0, float(cgpa)) * 10.0

    score = (cgpa_component * 0.7) + (income_component * 0.2) + bonus
    return round(score, 2)


def _parse_llm_score(content: str) -> Optional[float]:
    try:
        payload = json.loads(content)
        if isinstance(payload, dict) and "score" in payload:
            return float(payload["score"])
    except json.JSONDecodeError:
        pass

    match = re.search(r"-?\d+(?:\.\d+)?", content)
    if match:
        return float(match.group(0))
    return None


def compute_score_with_llm(income: int, cgpa: float, category: str, settings) -> float:
    if not getattr(settings, "llm_enabled", False):
        return compute_score(income, cgpa, category)

    prompt = (
        "You are a scoring function. Apply these rules exactly and return JSON only.\n"
        "Rules:\n"
        "category_bonus={general:0, obc:5, sc:10, st:12, ews:7}.\n"
        "income_component = max(0, 100 - income/1000).\n"
        "cgpa_component = min(10, cgpa) * 10.\n"
        "score = (cgpa_component * 0.7) + (income_component * 0.2) + category_bonus.\n"
        'Return: {"score": number}.\n\n'
        f"Input: income={income}, cgpa={cgpa}, category={category}" 
    )

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    payload = {
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "messages": [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": prompt},
        ],
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=settings.llm_timeout)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        score = _parse_llm_score(content)
        if score is None:
            raise ValueError("No score in LLM response")
        return round(float(score), 2)
    except Exception:
        return compute_score(income, cgpa, category)
