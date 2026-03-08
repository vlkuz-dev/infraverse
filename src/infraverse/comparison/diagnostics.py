"""Sync diagnostics: compute reasons for comparison discrepancies."""

from datetime import datetime

from infraverse.comparison.models import VMState
from infraverse.db.models import SyncRun

# Maps discrepancy labels to the sync source that would resolve them.
_DISCREPANCY_SOURCE_MAP: dict[str, str] = {
    "in cloud but not in NetBox": "netbox",
    "in cloud but not in monitoring": "zabbix",
    "in NetBox but not in monitoring": "zabbix",
    "in monitoring but not in NetBox": "netbox",
}

# Discrepancies that can be explained by per-VM sync errors from SyncEngine.
_VM_ERROR_DISCREPANCIES = {
    "in cloud but not in NetBox",
}

# Reason templates per source and status.
# {time} = formatted timestamp, {error} = error message, {found} = items_found count.
_REASON_TEMPLATES: dict[str, dict[str | None, str]] = {
    "netbox": {
        None: "Импорт из NetBox ещё не запускался — расхождение может быть неточным",
        "running": "Импорт из NetBox выполняется — данные могут обновиться",
        "failed": "Импорт из NetBox завершился с ошибкой: {error} — данные могут быть устаревшими",
        "success": "Проверено {time} (найдено {found} хостов). VM нет в NetBox — необходимо создать",
    },
    "zabbix": {
        None: "Проверка мониторинга ещё не запускалась — расхождение может быть неточным",
        "running": "Проверка мониторинга выполняется — данные могут обновиться",
        "failed": "Проверка мониторинга завершилась с ошибкой: {error} — данные могут быть устаревшими",
        "success": "Проверено {time} (найдено {found} хостов). VM нет в мониторинге — необходимо подключить",
    },
}


def _format_time(dt: datetime | None) -> str:
    """Format datetime to a human-friendly local time string."""
    if dt is None:
        return "?"
    local_dt = dt.astimezone()
    return local_dt.strftime("%d.%m.%Y %H:%M")


def _get_reason(source: str, sync_run: SyncRun | None) -> str:
    """Pick a reason string based on source and latest SyncRun state."""
    templates = _REASON_TEMPLATES.get(source, {})
    if sync_run is None:
        return templates.get(None, f"Импорт из {source} ещё не запускался")

    status = sync_run.status
    if status == "failed":
        error = sync_run.error_message or "неизвестная ошибка"
        template = templates.get("failed", "Ошибка при импорте: {error}")
        return template.format(error=error)

    if status == "running":
        return templates.get("running", f"Импорт из {source} выполняется...")

    # success or any other terminal status
    time_str = _format_time(sync_run.finished_at or sync_run.started_at)
    found = sync_run.items_found or 0
    template = templates.get("success", f"VM отсутствует в {source}")
    return template.format(time=time_str, found=found)


def compute_sync_reasons(
    states: list[VMState],
    latest_sync_runs: dict[str, SyncRun | None],
    vm_sync_errors: dict[str, str] | None = None,
) -> None:
    """Annotate VMState.sync_reasons based on SyncRun data and per-VM errors.

    Modifies states in-place.

    Args:
        states: List of VMState objects with discrepancies already computed.
        latest_sync_runs: Mapping of source name -> latest SyncRun (or None).
        vm_sync_errors: Optional mapping of vm_name -> last_sync_error from DB.
            When a VM has a sync error for a NetBox-related discrepancy,
            it takes priority over the generic SyncRun-based reason.
    """
    errors = vm_sync_errors or {}
    for state in states:
        for discrepancy in state.discrepancies:
            # Check for per-VM sync error first (e.g. SyncEngine failed for this VM)
            vm_error = errors.get(state.vm_name)
            if vm_error and discrepancy in _VM_ERROR_DISCREPANCIES:
                state.sync_reasons[discrepancy] = (
                    f"Ошибка синхронизации в NetBox: {vm_error}"
                )
                continue

            source = _DISCREPANCY_SOURCE_MAP.get(discrepancy)
            if source is None:
                continue
            sync_run = latest_sync_runs.get(source)
            state.sync_reasons[discrepancy] = _get_reason(source, sync_run)
