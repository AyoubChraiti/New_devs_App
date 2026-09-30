import json
import redis.asyncio as redis
from typing import Dict, Any
import os

# Initialize Redis client (typically configured centrally).
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

async def get_revenue_summary(property_id: str, tenant_id: str, *, month: int | None = None,
                              year: int | None = None, timezone_name: str | None = None) -> Dict[str, Any]:
    """
    Fetches revenue summary, utilizing caching to improve performance.
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("Tenant identity is required for revenue summaries")

    # Version the namespace to bypass legacy shared entries and previously cached mock totals.
    # JSON encoding keeps tenant/property pairs distinct even if IDs contain ':'.
    cache_key = "revenue:v5:all:" + json.dumps([tenant_id, property_id], separators=(",", ":"))
    
    if (month is None) != (year is None):
        raise ValueError("Month and year must be supplied together")
    if month is not None:
        if not timezone_name or not 1 <= month <= 12 or not 1 <= year <= 9998:
            raise ValueError("Invalid monthly reporting period or time zone")
        cache_key = "revenue:v5:monthly:" + json.dumps(
            [tenant_id, property_id, year, month, timezone_name], separators=(",", ":")
        )

    # Try to get from cache
    cached = await redis_client.get(cache_key)
    if cached:
        try:
            payload = json.loads(cached)
        except (ValueError, UnicodeDecodeError):
            payload = None
        if (
            isinstance(payload, dict)
            and payload.get("tenant_id") == tenant_id
            and payload.get("property_id") == property_id
            and (month is None or (
                payload.get("month") == month and payload.get("year") == year
                and payload.get("timezone") == timezone_name
            ))
        ):
            return payload
    
    # Revenue calculation is delegated to the reservation service.
    from app.services.reservations import calculate_total_revenue
    
    # Calculate revenue
    if month is None:
        result = await calculate_total_revenue(property_id, tenant_id)
    else:
        from app.services.reservations import calculate_monthly_revenue
        result = await calculate_monthly_revenue(property_id, tenant_id, month, year, timezone_name)
    
    # Cache the result for 5 minutes
    await redis_client.setex(cache_key, 300, json.dumps(result))
    
    return result
