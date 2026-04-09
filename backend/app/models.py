from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ApplicationIn(BaseModel):
    applicant_id: str = Field(..., min_length=3, max_length=64)
    name: str = Field(..., min_length=2, max_length=128)
    income: int = Field(..., ge=0)
    cgpa: float = Field(..., ge=0, le=10)
    category: str = Field(..., min_length=2, max_length=32)


class ApplicationOut(BaseModel):
    applicant_id: str
    name: str
    income: int
    cgpa: float
    category: str
    score: float
    created_at: str
    allocated: bool
    allocated_amount: int
    income_certificate: Optional[str] = None
    caste_certificate: Optional[str] = None


class LeaderboardEntry(BaseModel):
    applicant_id: str
    name: str
    category: str
    score: float
    allocated: bool
    allocated_amount: int


class BudgetStatus(BaseModel):
    total_budget: int
    remaining_budget: int


class AllocationResult(BaseModel):
    allocated_count: int
    remaining_budget: int
    selected: List[LeaderboardEntry]


class DashboardOut(BaseModel):
    leaderboard: List[LeaderboardEntry]
    fund_utilization: BudgetStatus
    selected_candidates: List[LeaderboardEntry]
    last_updated: str


class RulesOut(BaseModel):
    category_quota: Dict[str, float]
    grant_per_student: int
    grant_by_category: Dict[str, int]
    income_cap: int
    cgpa_min: float
