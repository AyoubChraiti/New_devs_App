import json
import redis.asyncio as redis
from typing import Dict, Any
import os

# Initialize Redis client (typically configured centrally).
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

async def get_revenue_summary(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Fetches revenue summary, utilizing caching to improve performance.
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("Tenant identity is required for revenue summaries")

    # Version the namespace to bypass legacy shared entries and previously cached mock totals.
    # JSON encoding keeps tenant/property pairs distinct even if IDs contain ':'.
    cache_key = "revenue:v3:" + json.dumps([tenant_id, property_id], separators=(",", ":"))
    
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
        ):
            return payload
    
    # Revenue calculation is delegated to the reservation service.
    from app.services.reservations import calculate_total_revenue
    
    # Calculate revenue
    result = await calculate_total_revenue(property_id, tenant_id)
    
    # Cache the result for 5 minutes
    await redis_client.setex(cache_key, 300, json.dumps(result))
    
    return result
