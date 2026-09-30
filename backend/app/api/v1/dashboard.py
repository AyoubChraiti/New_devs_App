from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from app.services.cache import get_revenue_summary
from app.services.reservations import RevenueUnavailableError
from app.services.properties import get_tenant_properties, PropertiesUnavailableError
from app.core.auth import authenticate_request as get_current_user

router = APIRouter()

def get_tenant_id(current_user=Depends(get_current_user)) -> str:
    tenant_id = getattr(current_user, "tenant_id", None)
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise HTTPException(status_code=403, detail="Tenant identity is required")
    return tenant_id


@router.get("/dashboard/properties")
async def get_dashboard_properties(tenant_id: str = Depends(get_tenant_id)):
    try:
        return await get_tenant_properties(tenant_id)
    except PropertiesUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Properties are temporarily unavailable") from exc


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str,
    tenant_id: str = Depends(get_tenant_id)
) -> Dict[str, Any]:
    try:
        # Always authorize before reading revenue, including on a cache hit.
        if not await get_tenant_properties(tenant_id, property_id):
            raise HTTPException(status_code=404, detail="Property not found")
        revenue_data = await get_revenue_summary(property_id, tenant_id)
    except (PropertiesUnavailableError, RevenueUnavailableError) as exc:
        raise HTTPException(status_code=503, detail="Revenue is temporarily unavailable") from exc

    total_revenue_float = float(revenue_data['total'])
    return {
        "property_id": revenue_data['property_id'],
        "total_revenue": total_revenue_float,
        "currency": revenue_data['currency'],
        "reservations_count": revenue_data['count']
    }
