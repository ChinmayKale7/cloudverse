import asyncio
from datetime import datetime
from typing import Dict, List

import boto3
from boto3.dynamodb.conditions import Attr, Key

from .repository import Repository


BUDGET_KEY = "__BUDGET__"
LEADERBOARD_PK = "leaderboard"
LEADERBOARD_INDEX = "LeaderboardIndex"


class DynamoDBRepository(Repository):
    def __init__(self, table_name: str, region: str, total_budget: int):
        self.table_name = table_name
        self.region = region
        self.total_budget = total_budget
        self.resource = boto3.resource("dynamodb", region_name=region)
        self.table = self.resource.Table(table_name)

    async def init(self) -> None:
        def _init() -> None:
            try:
                self.table.put_item(
                    Item={
                        "applicant_id": BUDGET_KEY,
                        "item_type": "budget",
                        "total_budget": self.total_budget,
                        "remaining_budget": self.total_budget,
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                    ConditionExpression="attribute_not_exists(applicant_id)",
                )
            except self.resource.meta.client.exceptions.ConditionalCheckFailedException:
                pass

        await asyncio.to_thread(_init)

    async def create_application(self, application: Dict) -> Dict:
        def _create() -> Dict:
            gsi_pk, gsi_sk = self._build_gsi_keys(application["score"], application["created_at"])
            try:
                self.table.put_item(
                    Item={
                        **application,
                        "item_type": "application",
                        "allocated": False,
                        "allocated_amount": 0,
                        "gsi_pk": gsi_pk,
                        "gsi_sk": gsi_sk,
                    },
                    ConditionExpression="attribute_not_exists(applicant_id)",
                )
            except self.resource.meta.client.exceptions.ConditionalCheckFailedException:
                raise ValueError("duplicate")
            return {**application, "allocated": False, "allocated_amount": 0}

        return await asyncio.to_thread(_create)

    async def list_leaderboard(self, limit: int) -> List[Dict]:
        def _list() -> List[Dict]:
            response = self.table.query(
                IndexName=LEADERBOARD_INDEX,
                KeyConditionExpression=Key("gsi_pk").eq(LEADERBOARD_PK),
                Limit=limit,
                ScanIndexForward=True,
            )
            sliced = response.get("Items", [])
            return [
                {
                    "applicant_id": i["applicant_id"],
                    "name": i["name"],
                    "category": i["category"],
                    "score": float(i["score"]),
                    "allocated": bool(i.get("allocated", False)),
                    "allocated_amount": int(i.get("allocated_amount", 0)),
                }
                for i in sliced
            ]

        return await asyncio.to_thread(_list)

    async def list_selected(self) -> List[Dict]:
        def _list() -> List[Dict]:
            response = self.table.query(
                IndexName=LEADERBOARD_INDEX,
                KeyConditionExpression=Key("gsi_pk").eq(LEADERBOARD_PK),
                FilterExpression=Attr("allocated").eq(True),
                Limit=500,
                ScanIndexForward=True,
            )
            items = response.get("Items", [])
            return [
                {
                    "applicant_id": i["applicant_id"],
                    "name": i["name"],
                    "category": i["category"],
                    "score": float(i["score"]),
                    "allocated": True,
                    "allocated_amount": int(i.get("allocated_amount", 0)),
                }
                for i in items
            ]

        return await asyncio.to_thread(_list)

    async def get_budget(self) -> Dict:
        def _get() -> Dict:
            response = self.table.get_item(Key={"applicant_id": BUDGET_KEY})
            item = response.get("Item")
            if not item:
                return {"total_budget": self.total_budget, "remaining_budget": self.total_budget}
            return {
                "total_budget": int(item["total_budget"]),
                "remaining_budget": int(item["remaining_budget"]),
            }

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
            budget_item = self.table.get_item(Key={"applicant_id": BUDGET_KEY}).get("Item")
            remaining_budget = (
                int(budget_item["remaining_budget"]) if budget_item else self.total_budget
            )
            min_grant = min(grant_by_category.values() or [grant_per_student])
            if remaining_budget < min_grant:
                return {"allocated_count": 0, "remaining_budget": remaining_budget, "selected": []}

            total_slots = min(limit, remaining_budget // min_grant)
            category_caps = {
                category: int(total_slots * quota)
                for category, quota in category_quota.items()
            }
            category_counts = {category: 0 for category in category_quota.keys()}
            allocated = []
            start_key = None
            budget_exhausted = False
            while len(allocated) < limit:
                query_args = {
                    "IndexName": LEADERBOARD_INDEX,
                    "KeyConditionExpression": Key("gsi_pk").eq(LEADERBOARD_PK),
                    "Limit": 200,
                    "ScanIndexForward": True,
                }
                if start_key:
                    query_args["ExclusiveStartKey"] = start_key
                response = self.table.query(**query_args)
                items = response.get("Items", [])
                start_key = response.get("LastEvaluatedKey")
                if not items:
                    break

                for item in items:
                    if len(allocated) >= limit:
                        break
                    if item.get("allocated"):
                        continue
                    category = item.get("category")
                    cgpa = float(item.get("cgpa", 0))
                    income = int(item.get("income", 0))
                    income_cert = item.get("income_certificate")
                    caste_cert = item.get("caste_certificate")
                    grant_amount = int(grant_by_category.get(category, grant_per_student))
                    if remaining_budget < grant_amount:
                        budget_exhausted = True
                        break
                    if income > income_cap or not income_cert:
                        continue
                    if category != "general" and not caste_cert:
                        continue
                    if cgpa < cgpa_min:
                        continue
                    if category in category_caps and category_counts[category] >= category_caps[category]:
                        continue
                    try:
                        self.resource.meta.client.transact_write_items(
                            TransactItems=[
                                {
                                    "Update": {
                                        "TableName": self.table_name,
                                        "Key": {"applicant_id": {"S": BUDGET_KEY}},
                                        "UpdateExpression": "SET remaining_budget = remaining_budget - :g, updated_at = :u",
                                        "ConditionExpression": "remaining_budget >= :g",
                                        "ExpressionAttributeValues": {
                                            ":g": {"N": str(grant_amount)},
                                            ":u": {"S": datetime.utcnow().isoformat()},
                                        },
                                    }
                                },
                                {
                                    "Update": {
                                        "TableName": self.table_name,
                                        "Key": {"applicant_id": {"S": item["applicant_id"]}},
                                        "UpdateExpression": "SET allocated = :t, allocated_amount = :g",
                                        "ConditionExpression": "allocated = :f OR attribute_not_exists(allocated)",
                                        "ExpressionAttributeValues": {
                                            ":t": {"BOOL": True},
                                            ":f": {"BOOL": False},
                                            ":g": {"N": str(grant_amount)},
                                        },
                                    }
                                },
                            ]
                        )
                    except self.resource.meta.client.exceptions.TransactionCanceledException:
                        budget_exhausted = True
                        break

                    allocated.append(
                        {
                            "applicant_id": item["applicant_id"],
                            "name": item["name"],
                            "category": item["category"],
                            "score": float(item["score"]),
                            "allocated": True,
                            "allocated_amount": grant_amount,
                        }
                    )
                    if category in category_counts:
                        category_counts[category] += 1

                if budget_exhausted or not start_key:
                    break

            budget = self.table.get_item(Key={"applicant_id": BUDGET_KEY}).get("Item")
            remaining_budget = int(budget["remaining_budget"]) if budget else self.total_budget
            return {
                "allocated_count": len(allocated),
                "remaining_budget": remaining_budget,
                "selected": allocated,
            }

        return await asyncio.to_thread(_allocate)

    async def reset_data(self) -> Dict:
        def _reset() -> Dict:
            deleted = 0
            scan_kwargs = {
                "ProjectionExpression": "applicant_id",
                "FilterExpression": Attr("applicant_id").ne(BUDGET_KEY),
            }
            while True:
                response = self.table.scan(**scan_kwargs)
                items = response.get("Items", [])
                if items:
                    with self.table.batch_writer() as batch:
                        for item in items:
                            batch.delete_item(Key={"applicant_id": item["applicant_id"]})
                            deleted += 1
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
                scan_kwargs["ExclusiveStartKey"] = last_key

            budget_item = {
                "applicant_id": BUDGET_KEY,
                "item_type": "budget",
                "total_budget": self.total_budget,
                "remaining_budget": self.total_budget,
                "updated_at": datetime.utcnow().isoformat(),
            }
            self.table.put_item(Item=budget_item)
            return {
                "cleared_applications": deleted,
                "budget": {
                    "total_budget": self.total_budget,
                    "remaining_budget": self.total_budget,
                },
            }

        return await asyncio.to_thread(_reset)

    @staticmethod
    def _build_gsi_keys(score: float, created_at: str) -> tuple[str, str]:
        # Lower gsi_sk sorts first, so invert score to get descending score order.
        score_rank = max(0.0, 1000.0 - float(score))
        return LEADERBOARD_PK, f"{score_rank:07.2f}#{created_at}"
