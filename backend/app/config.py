import json
from typing import Dict

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Scholarship Eligibility API"
    db_backend: str = "sqlite"  # sqlite or dynamodb
    sqlite_path: str = "backend/data/app.db"
    aws_region: str = "us-east-1"
    dynamodb_table: str = "ScholarshipApplications"
    grant_per_student: int = 1000
    total_budget: int = 100000
    dashboard_limit: int = 50
    cors_origins: str = "*"
    income_cap: int = 800000
    cgpa_min: float = 8.5
    category_quota_json: str = (
        '{"general": 0.4, "obc": 0.25, "sc": 0.2, "st": 0.1, "ews": 0.05}'
    )
    grant_by_category_json: str = (
        '{"general": 800, "obc": 1000, "sc": 1200, "st": 1400, "ews": 1000}'
    )
    admin_token: str = ""
    llm_enabled: bool = False
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout: int = 15
    llm_temperature: float = 0.0

    class Config:
        env_file = ("backend/.env", ".env")
        case_sensitive = False


settings = Settings()


def parse_category_quota() -> Dict[str, float]:
    return json.loads(settings.category_quota_json)


def parse_grant_by_category() -> Dict[str, int]:
    return json.loads(settings.grant_by_category_json)
