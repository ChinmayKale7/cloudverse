import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import (
    parse_category_quota,
    parse_grant_by_category,
    settings,
)
from .db.dynamo_repo import DynamoDBRepository
from .db.repository import Repository
from .db.sqlite_repo import SQLiteRepository
from .models import (
    AllocationResult,
    ApplicationOut,
    DashboardOut,
    LeaderboardEntry,
    RulesOut,
)
from .services.scoring import compute_score_with_llm


def build_repository() -> Repository:
    backend = settings.db_backend.strip().lower()
    if backend == "dynamodb":
        return DynamoDBRepository(
            table_name=settings.dynamodb_table,
            region=settings.aws_region,
            total_budget=settings.total_budget,
        )
    return SQLiteRepository(settings.sqlite_path, settings.total_budget)


app = FastAPI(title=settings.app_name)
repo = build_repository()

cors_raw = settings.cors_origins.strip()
cors_list = [origin.strip() for origin in cors_raw.split(",") if origin.strip()]
allow_origins = ["*"] if cors_raw == "*" else cors_list
allow_origin_regex = ".*" if cors_raw == "*" else None

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    await repo.init()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/applications", response_model=ApplicationOut)
async def submit_application(
    applicant_id: str = Form(...),
    name: str = Form(...),
    income: int = Form(...),
    cgpa: float = Form(...),
    category: str = Form(...),
    income_certificate: UploadFile = File(...),
    caste_certificate: Optional[UploadFile] = File(None),
) -> ApplicationOut:
    normalized_category = category.strip().lower()
    if normalized_category != "general" and not caste_certificate:
        raise HTTPException(status_code=400, detail="Caste certificate required")

    upload_dir = Path("backend/data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    income_path = upload_dir / f"{applicant_id}_income_{income_certificate.filename}"
    income_path.write_bytes(await income_certificate.read())
    caste_path = None
    if caste_certificate:
        caste_path = upload_dir / f"{applicant_id}_caste_{caste_certificate.filename}"
        caste_path.write_bytes(await caste_certificate.read())

    score = await asyncio.to_thread(
        compute_score_with_llm,
        income,
        cgpa,
        normalized_category,
        settings,
    )
    application = {
        "applicant_id": applicant_id,
        "name": name,
        "income": income,
        "marks": int(round(cgpa * 10)),
        "cgpa": cgpa,
        "category": normalized_category,
        "score": score,
        "created_at": datetime.utcnow().isoformat(),
        "income_certificate": str(income_path),
        "caste_certificate": str(caste_path) if caste_path else None,
    }
    try:
        stored = await repo.create_application(application)
    except ValueError:
        income_path.unlink(missing_ok=True)
        if caste_path:
            caste_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="Application already exists")
    return ApplicationOut(**stored)


@app.get("/leaderboard", response_model=List[LeaderboardEntry])
async def get_leaderboard(limit: int = Query(50, ge=1, le=500)) -> List[LeaderboardEntry]:
    return [LeaderboardEntry(**item) for item in await repo.list_leaderboard(limit)]


@app.post("/allocate", response_model=AllocationResult)
async def allocate_funds(limit: int = Query(200, ge=1, le=1000)) -> AllocationResult:
    result = await repo.allocate_funds(
        settings.grant_per_student,
        limit,
        parse_category_quota(),
        settings.income_cap,
        settings.cgpa_min,
        parse_grant_by_category(),
    )
    return AllocationResult(**result)


@app.get("/dashboard", response_model=DashboardOut)
async def get_dashboard(limit: int = Query(50, ge=1, le=500)) -> DashboardOut:
    leaderboard = await repo.list_leaderboard(limit)
    selected = await repo.list_selected()
    budget = await repo.get_budget()
    return DashboardOut(
        leaderboard=[LeaderboardEntry(**entry) for entry in leaderboard],
        fund_utilization=budget,
        selected_candidates=[LeaderboardEntry(**entry) for entry in selected],
        last_updated=datetime.utcnow().isoformat(),
    )


@app.get("/rules", response_model=RulesOut)
async def get_rules() -> RulesOut:
    return RulesOut(
        category_quota=parse_category_quota(),
        grant_per_student=settings.grant_per_student,
        grant_by_category=parse_grant_by_category(),
        income_cap=settings.income_cap,
        cgpa_min=settings.cgpa_min,
    )


@app.post("/admin/reset")
async def reset_data(
    confirm: bool = Query(False),
    admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
) -> dict:
    if not confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to reset data")
    if settings.admin_token and admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await repo.reset_data()
    upload_dir = Path("backend/data/uploads")
    removed_files = 0
    if upload_dir.exists():
        for file_path in upload_dir.iterdir():
            if file_path.is_file():
                file_path.unlink(missing_ok=True)
                removed_files += 1

    return {
        "cleared_applications": result.get("cleared_applications", 0),
        "uploads_removed": removed_files,
        "budget": result.get("budget"),
    }
