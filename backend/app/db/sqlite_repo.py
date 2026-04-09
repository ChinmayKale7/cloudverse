import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .repository import Repository


class SQLiteRepository(Repository):
    def __init__(self, db_path: str, total_budget: int):
        self.db_path = db_path
        self.total_budget = total_budget

    async def init(self) -> None:
        def _init() -> None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    applicant_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    income INTEGER NOT NULL,
                    marks INTEGER NOT NULL,
                    cgpa REAL NOT NULL DEFAULT 0,
                    category TEXT NOT NULL,
                    score REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    allocated INTEGER NOT NULL DEFAULT 0,
                    allocated_amount INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            columns = [row[1] for row in conn.execute("PRAGMA table_info(applications)").fetchall()]
            missing_columns = {
                "scheme": "TEXT",
                "income_certificate": "TEXT",
                "caste_certificate": "TEXT",
                "cgpa": "REAL",
            }
            for column, col_type in missing_columns.items():
                if column not in columns:
                    conn.execute(f"ALTER TABLE applications ADD COLUMN {column} {col_type}")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS budget (
                    id INTEGER PRIMARY KEY,
                    total_budget INTEGER NOT NULL,
                    remaining_budget INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            existing = conn.execute("SELECT COUNT(1) FROM budget").fetchone()[0]
            if existing == 0:
                conn.execute(
                    "INSERT INTO budget (id, total_budget, remaining_budget, updated_at) VALUES (1, ?, ?, ?)",
                    (self.total_budget, self.total_budget, datetime.utcnow().isoformat()),
                )
            conn.commit()
            conn.close()

        await asyncio.to_thread(_init)

    async def create_application(self, application: Dict) -> Dict:
        def _create() -> Dict:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO applications (
                        applicant_id, name, income, marks, cgpa, category, score, created_at,
                        allocated, allocated_amount, scheme, income_certificate, caste_certificate
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
                    """,
                    (
                        application["applicant_id"],
                        application["name"],
                        application["income"],
                        application["marks"],
                        application.get("cgpa", 0),
                        application["category"],
                        application["score"],
                        application["created_at"],
                        application.get("scheme"),
                        application.get("income_certificate"),
                        application.get("caste_certificate"),
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError("duplicate")
            finally:
                conn.close()
            return application

        return await asyncio.to_thread(_create)

    async def list_leaderboard(self, limit: int) -> List[Dict]:
        def _list() -> List[Dict]:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """
                SELECT applicant_id, name, category, score, allocated, allocated_amount
                FROM applications
                ORDER BY score DESC, created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            conn.close()
            return [
                {
                    "applicant_id": r[0],
                    "name": r[1],
                    "category": r[2],
                    "score": r[3],
                    "allocated": bool(r[4]),
                    "allocated_amount": r[5],
                }
                for r in rows
            ]

        return await asyncio.to_thread(_list)

    async def list_selected(self) -> List[Dict]:
        def _list() -> List[Dict]:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """
                SELECT applicant_id, name, category, score, allocated, allocated_amount
                FROM applications
                WHERE allocated = 1
                ORDER BY score DESC, created_at ASC
                """
            ).fetchall()
            conn.close()
            return [
                {
                    "applicant_id": r[0],
                    "name": r[1],
                    "category": r[2],
                    "score": r[3],
                    "allocated": bool(r[4]),
                    "allocated_amount": r[5],
                }
                for r in rows
            ]

        return await asyncio.to_thread(_list)

    async def get_budget(self) -> Dict:
        def _get() -> Dict:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT total_budget, remaining_budget FROM budget WHERE id = 1"
            ).fetchone()
            conn.close()
            return {"total_budget": row[0], "remaining_budget": row[1]}

        return await asyncio.to_thread(_get)

    async def allocate_funds(
        self,
        grant_per_student: int,
        limit: int,
        category_quota: Dict[str, float],
        income_cap: int,
        cgpa_min: float,
        grant_by_category: Dict[str, int],
    ) -> Dict:
        def _allocate() -> Dict:
            conn = sqlite3.connect(self.db_path)
            conn.isolation_level = None
            try:
                conn.execute("BEGIN IMMEDIATE")
                total_budget, remaining_budget = conn.execute(
                    "SELECT total_budget, remaining_budget FROM budget WHERE id = 1"
                ).fetchone()
                min_grant = min(grant_by_category.values() or [grant_per_student])
                if remaining_budget < min_grant:
                    conn.execute("COMMIT")
                    return {
                        "allocated_count": 0,
                        "remaining_budget": remaining_budget,
                        "selected": [],
                    }

                total_slots = min(limit, remaining_budget // min_grant)
                category_caps = {
                    category: int(total_slots * quota)
                    for category, quota in category_quota.items()
                }
                category_counts = {category: 0 for category in category_quota.keys()}

                rows = conn.execute(
                    """
                    SELECT applicant_id, name, category, score, allocated, allocated_amount, marks, income,
                           income_certificate, caste_certificate, cgpa
                    FROM applications
                    WHERE allocated = 0
                    ORDER BY score DESC, created_at ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

                allocated = []
                for r in rows:
                    applicant_id = r[0]
                    category = r[2]
                    marks = r[6]
                    income = r[7]
                    income_cert = r[8]
                    caste_cert = r[9]
                    cgpa = float(r[10] or 0)
                    grant_amount = grant_by_category.get(category, grant_per_student)
                    if remaining_budget < grant_amount:
                        break
                    if income > income_cap or not income_cert:
                        continue
                    if category != "general" and not caste_cert:
                        continue
                    if cgpa < cgpa_min:
                        continue
                    if category in category_caps and category_counts[category] >= category_caps[category]:
                        continue
                    conn.execute(
                        """
                        UPDATE applications
                        SET allocated = 1, allocated_amount = ?
                        WHERE applicant_id = ? AND allocated = 0
                        """,
                        (grant_amount, applicant_id),
                    )
                    if conn.total_changes > 0:
                        remaining_budget -= grant_amount
                        if category in category_counts:
                            category_counts[category] += 1
                        allocated.append(
                            {
                                "applicant_id": r[0],
                                "name": r[1],
                                "category": r[2],
                                "score": r[3],
                                "allocated": True,
                                "allocated_amount": grant_amount,
                            }
                        )
                conn.execute(
                    "UPDATE budget SET remaining_budget = ?, updated_at = ? WHERE id = 1",
                    (remaining_budget, datetime.utcnow().isoformat()),
                )
                conn.execute("COMMIT")
                return {
                    "allocated_count": len(allocated),
                    "remaining_budget": remaining_budget,
                    "selected": allocated,
                }
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(_allocate)

    async def reset_data(self) -> Dict:
        def _reset() -> Dict:
            conn = sqlite3.connect(self.db_path)
            removed = conn.execute("SELECT COUNT(1) FROM applications").fetchone()[0]
            conn.execute("DELETE FROM applications")
            conn.execute(
                "INSERT OR REPLACE INTO budget (id, total_budget, remaining_budget, updated_at) VALUES (1, ?, ?, ?)",
                (self.total_budget, self.total_budget, datetime.utcnow().isoformat()),
            )
            conn.commit()
            conn.close()
            return {
                "cleared_applications": int(removed),
                "budget": {
                    "total_budget": self.total_budget,
                    "remaining_budget": self.total_budget,
                },
            }

        return await asyncio.to_thread(_reset)
