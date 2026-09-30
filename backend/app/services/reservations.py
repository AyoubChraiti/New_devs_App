from datetime import datetime
from decimal import Decimal
from typing import Dict, Any
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.core.database_pool import db_pool

logger = logging.getLogger(__name__)


class RevenueUnavailableError(Exception):
    """Revenue could not be read from its source database."""


async def calculate_monthly_revenue(property_id: str, month: int, year: int, db_session=None) -> Decimal:
    """
    Calculates revenue for a specific month.
    """

    start_date = datetime(year, month, 1)
    if month < 12:
        end_date = datetime(year, month + 1, 1)
    else:
        end_date = datetime(year + 1, 1, 1)
        
    print(f"DEBUG: Querying revenue for {property_id} from {start_date} to {end_date}")

    # SQL Simulation (This would be executed against the actual DB)
    query = """
        SELECT SUM(total_amount) as total
        FROM reservations
        WHERE property_id = $1
        AND tenant_id = $2
        AND check_in_date >= $3
        AND check_in_date < $4
    """
    
    # In production this query executes against a database session.
    # result = await db.fetch_val(query, property_id, tenant_id, start_date, end_date)
    # return result or Decimal('0')
    
    return Decimal('0') # Placeholder for now until DB connection is finalized

async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """Aggregate actual reservations, scoped to the authenticated tenant."""
    try:
        await db_pool.initialize()
        async with db_pool.get_session() as session:
            result = await session.execute(text("""
                SELECT COALESCE(SUM(total_amount), 0) AS total_revenue,
                       COUNT(*) AS reservation_count
                FROM reservations
                WHERE property_id = :property_id AND tenant_id = :tenant_id
            """), {"property_id": property_id, "tenant_id": tenant_id})
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
