from abc import ABC, abstractmethod
from typing import Dict, List


class Repository(ABC):
    @abstractmethod
    async def init(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def create_application(self, application: Dict) -> Dict:
        raise NotImplementedError

    @abstractmethod
    async def list_leaderboard(self, limit: int) -> List[Dict]:
        raise NotImplementedError

    @abstractmethod
    async def list_selected(self) -> List[Dict]:
        raise NotImplementedError

    @abstractmethod
    async def get_budget(self) -> Dict:
        raise NotImplementedError

    @abstractmethod
    async def allocate_funds(
        self,
        grant_per_student: int,
        limit: int,
        category_quota: Dict[str, float],
        income_cap: int,
        cgpa_min: float,
        grant_by_category: Dict[str, int],
    ) -> Dict:
        raise NotImplementedError

    @abstractmethod
    async def reset_data(self) -> Dict:
        raise NotImplementedError
