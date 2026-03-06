"""Sync trigger and status routes for Infraverse web UI."""

from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(prefix="/sync", tags=["sync"])


def _status_dict(scheduler) -> dict:
    if scheduler is None:
        return {
            "running": False,
            "next_run_time": None,
            "last_run_time": None,
            "last_result": None,
        }
    return scheduler.get_status()


def _status_html(status: dict) -> str:
    parts = []
    if status["running"]:
        parts.append('<span class="badge bg-green-lt me-2">Scheduler running</span>')
    else:
        parts.append('<span class="badge bg-secondary-lt me-2">Scheduler not active</span>')

    if status["next_run_time"]:
        parts.append(f'<span class="text-secondary me-3">Next run: {escape(str(status["next_run_time"]))}</span>')

    if status["last_run_time"]:
        parts.append(f'<span class="text-secondary me-3">Last run: {escape(str(status["last_run_time"]))}</span>')

    if status["last_result"]:
        if "error" in status["last_result"]:
            parts.append(f'<span class="text-danger">Error: {escape(str(status["last_result"]["error"]))}</span>')
        else:
            parts.append('<span class="text-success">Last sync successful</span>')

    return " ".join(parts) if parts else '<span class="text-secondary">No sync data</span>'


@router.post("/trigger")
def trigger_sync(request: Request):
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                '<span class="text-warning">Scheduler not configured. Set SYNC_INTERVAL_MINUTES &gt; 0.</span>'
            )
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not configured. Set SYNC_INTERVAL_MINUTES > 0."},
        )
    scheduler.trigger_now()
    status = scheduler.get_status()
    if request.headers.get("HX-Request"):
        return HTMLResponse(_status_html(status))
    return status


@router.get("/status")
def sync_status(request: Request):
    scheduler = getattr(request.app.state, "scheduler", None)
    status = _status_dict(scheduler)
    if request.headers.get("HX-Request"):
        return HTMLResponse(_status_html(status))
    return status
