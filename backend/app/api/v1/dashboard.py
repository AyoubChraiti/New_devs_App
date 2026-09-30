from fastapi import APIRouter, Depends, HTTPException, Query
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
    tenant_id: str = Depends(get_tenant_id),
    month: int | None = Query(default=None, ge=1, le=12),
    year: int | None = Query(default=None, ge=1, le=9998),
) -> Dict[str, Any]:
    if (month is None) != (year is None):
        raise HTTPException(status_code=422, detail="Month and year must be supplied together")
    try:
        # Always authorize before reading revenue, including on a cache hit.
        properties = await get_tenant_properties(tenant_id, property_id)
        if not properties:
            raise HTTPException(status_code=404, detail="Property not found")
        if month is None:
            revenue_data = await get_revenue_summary(property_id, tenant_id)
        else:
            revenue_data = await get_revenue_summary(
                property_id, tenant_id, month=month, year=year,
                timezone_name=properties[0]["timezone"],
            )
    except (PropertiesUnavailableError, RevenueUnavailableError) as exc:
        raise HTTPException(status_code=503, detail="Revenue is temporarily unavailable") from exc

    total_revenue_float = float(revenue_data['total'])
    return {
        "property_id": revenue_data['property_id'],
        "total_revenue": total_revenue_float,
        "currency": revenue_data['currency'],
        "reservations_count": revenue_data['count'],
        "month": month,
        "year": year,
        "timezone": properties[0].get("timezone"),
    }
