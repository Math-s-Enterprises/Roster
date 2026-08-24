"""Multi-tenant scoping.

THE PROBLEM THIS SOLVES
-----------------------
Every shop's data lives in shared collections, separated only by a
`shop_id` field. In the prototype, isolation depended on every single
query remembering to include `{"shop_id": ...}` by hand — roughly forty
places. One omission (easy when copy-pasting a route) turns into a
cross-tenant data leak: shop A reading or deleting shop B's records.

THE FIX
-------
`ShopScope` binds a shop_id once, at the start of the request, and builds
every filter itself. Route code cannot express an unscoped query through
it, so the failure mode is structurally removed rather than guarded by
discipline.

Routes obtain one via `Depends(get_shop_scope)` and use `scope.employees`,
`scope.rosters`, etc.
"""
from typing import Any, Dict, List, Optional

from fastapi import Depends

from app import db
from app.security import get_current_user

# Hard ceiling on any single unpaginated read, so a runaway collection can
# never load unbounded documents into memory.
MAX_PAGE_SIZE = 1000
DEFAULT_PAGE_SIZE = 500


class ScopedCollection:
    """A Motor collection with `shop_id` welded into every filter."""

    def __init__(self, collection, shop_id: str):
        self._collection = collection
        self._shop_id = shop_id

    def _filter(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query: Dict[str, Any] = {"shop_id": self._shop_id}
        if extra:
            # Callers must not be able to override the tenant boundary, even
            # accidentally, so shop_id is applied last.
            query.update(extra)
            query["shop_id"] = self._shop_id
        return query

    async def find(
        self,
        extra: Optional[Dict[str, Any]] = None,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        skip: int = 0,
        sort: Optional[List[tuple]] = None,
    ) -> List[Dict[str, Any]]:
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        cursor = self._collection.find(self._filter(extra), {"_id": 0})
        if sort:
            cursor = cursor.sort(sort)
        if skip:
            cursor = cursor.skip(skip)
        return await cursor.to_list(limit)

    def stream(self, extra: Optional[Dict[str, Any]] = None):
        """Async iterator for full scans that must not be truncated.

        Used where correctness depends on seeing every document (e.g.
        computing holiday balances across all approved rosters).
        """
        return self._collection.find(self._filter(extra), {"_id": 0})

    async def find_one(self, extra: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        return await self._collection.find_one(self._filter(extra), {"_id": 0})

    async def count(self, extra: Optional[Dict[str, Any]] = None) -> int:
        return await self._collection.count_documents(self._filter(extra))

    async def insert(self, document: Dict[str, Any]) -> Dict[str, Any]:
        payload = {**document, "shop_id": self._shop_id}
        # insert_one mutates the dict it receives (adds _id), so pass a copy
        # and return the clean version.
        await self._collection.insert_one(dict(payload))
        return payload

    async def update_one(self, extra: Dict[str, Any], changes: Dict[str, Any]) -> int:
        result = await self._collection.update_one(self._filter(extra), {"$set": changes})
        return result.modified_count

    async def delete_one(self, extra: Dict[str, Any]) -> int:
        result = await self._collection.delete_one(self._filter(extra))
        return result.deleted_count

    async def delete_many(self, extra: Optional[Dict[str, Any]] = None) -> int:
        result = await self._collection.delete_many(self._filter(extra))
        return result.deleted_count


class ShopScope:
    """All collections a request may touch, pre-bound to one shop."""

    def __init__(self, shop: Dict[str, Any], user: Dict[str, Any]):
        self.shop = shop
        self.user = user
        self.shop_id: str = shop["shop_id"]

        self.employees = ScopedCollection(db.employees, self.shop_id)
        self.holidays = ScopedCollection(db.holidays, self.shop_id)
        self.fixed_shifts = ScopedCollection(db.fixed_shifts, self.shop_id)
        self.ai_rules = ScopedCollection(db.ai_rules, self.shop_id)
        self.rosters = ScopedCollection(db.rosters, self.shop_id)
        self.activity_logs = ScopedCollection(db.activity_logs, self.shop_id)
        self.imports = ScopedCollection(db.roster_imports, self.shop_id)


async def get_shop_scope(user: Dict[str, Any] = Depends(get_current_user)) -> ShopScope:
    # Imported here rather than at module level to avoid a circular import
    # (shop_service imports tenancy for type hints).
    from app.services.shop_service import ensure_shop

    shop = await ensure_shop(user)
    return ShopScope(shop, user)


CurrentScope = Depends(get_shop_scope)
