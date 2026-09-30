from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Dict, Any
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.core.database_pool import db_pool

logger = logging.getLogger(__name__)


class RevenueUnavailableError(Exception):
    """Revenue could not be read from its source database."""


def monthly_utc_bounds(year: int, month: int, timezone_name: str):
    """Convert local calendar boundaries independently so DST offsets are correct."""
    if not 1 <= year <= 9998 or not 1 <= month <= 12:
        raise ValueError("Invalid reporting month")
    zone = ZoneInfo(timezone_name)
    start = datetime(year, month, 1, tzinfo=zone)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


async def calculate_monthly_revenue(property_id: str, tenant_id: str, month: int,
                                    year: int, timezone_name: str) -> Dict[str, Any]:
    try:
        start, end = monthly_utc_bounds(year, month, timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise RevenueUnavailableError("Invalid property reporting time zone or period") from exc
    result = await _calculate_revenue(property_id, tenant_id, start, end)
    return {**result, "month": month, "year": year, "timezone": timezone_name}


async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """Aggregate actual reservations, scoped to the authenticated tenant."""
    return await _calculate_revenue(property_id, tenant_id)


async def _calculate_revenue(property_id: str, tenant_id: str,
                             start: datetime | None = None, end: datetime | None = None) -> Dict[str, Any]:
    query = """
        SELECT COALESCE(SUM(total_amount), 0) AS total_revenue,
               COUNT(*) AS reservation_count
        FROM reservations
        WHERE property_id = :property_id AND tenant_id = :tenant_id
    """
    params = {"property_id": property_id, "tenant_id": tenant_id}
    if start is not None:
        query += " AND check_in_date >= :start AND check_in_date < :end"
        params.update(start=start, end=end)
    try:
        await db_pool.initialize()
        async with db_pool.get_session() as session:
            result = await session.execute(text(query), params)
            row = result.one()
            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": str(row.total_revenue),
                "currency": "USD",
                "count": row.reservation_count,
            }
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.exception("Revenue database query failed for tenant %s, property %s",
                         tenant_id, property_id)
        raise RevenueUnavailableError("Revenue is temporarily unavailable") from exc
