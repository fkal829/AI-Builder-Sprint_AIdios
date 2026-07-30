from fastapi import APIRouter

from app.api.v1.endpoints import (
    contracts,
    dashboard,
    health,
    mock_storage,
    public,
    webhooks,
)

router = APIRouter()
router.include_router(health.router, prefix="/health", tags=["health"])
router.include_router(mock_storage.router, prefix="/_mock/storage")
router.include_router(contracts.router, prefix="/contracts", tags=["contracts"])
router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
router.include_router(public.router, prefix="/public", tags=["public"])
router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
