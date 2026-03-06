"""Combined router for all Infraverse web routes."""

from fastapi import APIRouter

from infraverse.web.routes.dashboard import router as dashboard_router
from infraverse.web.routes.comparison import router as comparison_router
from infraverse.web.routes.sync import router as sync_router
from infraverse.web.routes.vms import router as vms_router

router = APIRouter()
router.include_router(dashboard_router)
router.include_router(comparison_router)
router.include_router(sync_router)
router.include_router(vms_router)
