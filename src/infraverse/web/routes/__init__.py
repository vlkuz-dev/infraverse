"""Combined router for all Infraverse web routes."""

from fastapi import APIRouter

from infraverse.web.routes.dashboard import router as dashboard_router
from infraverse.web.routes.comparison import router as comparison_router

router = APIRouter()
router.include_router(dashboard_router)
router.include_router(comparison_router)
