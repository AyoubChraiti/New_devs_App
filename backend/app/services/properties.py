import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.database_pool import db_pool

logger = logging.getLogger(__name__)


class PropertiesUnavailableError(Exception):
    """The property directory could not be read."""


async def get_tenant_properties(tenant_id: str, property_id: str | None = None) -> list[dict[str, Any]]:
    """Read properties only within the authenticated tenant, optionally by ID."""
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("Tenant identity is required")
    query = "SELECT id, name, timezone FROM properties WHERE tenant_id = :tenant_id"
    params = {"tenant_id": tenant_id}
    if property_id is not None:
        query += " AND id = :property_id"
        params["property_id"] = property_id
    query += " ORDER BY name, id"
    try:
        await db_pool.initialize()
        async with db_pool.get_session() as session:
            result = await session.execute(text(query), params)
            return [dict(row) for row in result.mappings().all()]
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.exception("Property lookup failed for tenant %s", tenant_id)
        raise PropertiesUnavailableError("Properties are temporarily unavailable") from exc
