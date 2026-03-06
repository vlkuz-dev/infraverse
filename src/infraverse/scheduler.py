"""Scheduled data ingestion service using APScheduler."""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from infraverse.db.repository import Repository
from infraverse.sync.ingest import DataIngestor

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages periodic data ingestion from cloud providers and monitoring systems.

    Wraps APScheduler's BackgroundScheduler to run DataIngestor on a configurable
    interval. Supports on-demand triggering and status reporting.
    """

    def __init__(self, session_factory, config):
        self._scheduler = BackgroundScheduler()
        self._session_factory = session_factory
        self._config = config
        self._last_result: dict | None = None
        self._last_run_time: datetime | None = None
        self._running = False

    def start(self, interval_minutes: int) -> None:
        """Start the scheduler with the given interval.

        Args:
            interval_minutes: Minutes between ingestion runs.
        """
        self._scheduler.add_job(
            self._run_ingestion,
            "interval",
            minutes=interval_minutes,
            id="ingestion",
            replace_existing=True,
        )
        self._scheduler.start()
        self._running = True
        logger.info("Scheduler started with interval=%d minutes", interval_minutes)

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("Scheduler stopped")

    def trigger_now(self) -> None:
        """Trigger an immediate ingestion run outside the regular schedule."""
        job = self._scheduler.get_job("ingestion")
        if job is not None:
            job.modify(next_run_time=datetime.now(timezone.utc))
        else:
            self._scheduler.add_job(
                self._run_ingestion,
                id="ingestion_manual",
                replace_existing=True,
            )
        logger.info("Ingestion triggered manually")

    def get_status(self) -> dict:
        """Return current scheduler state.

        Returns:
            Dict with keys: running, next_run_time, last_run_time, last_result.
        """
        next_run_time = None
        job = self._scheduler.get_job("ingestion")
        if job is not None and job.next_run_time is not None:
            next_run_time = job.next_run_time.isoformat()

        return {
            "running": self._running,
            "next_run_time": next_run_time,
            "last_run_time": self._last_run_time.isoformat() if self._last_run_time else None,
            "last_result": self._last_result,
        }

    def _run_ingestion(self) -> None:
        """Execute a full ingestion cycle using DataIngestor."""
        logger.info("Starting scheduled ingestion")
        session = self._session_factory()
        try:
            ingestor = DataIngestor(session)

            repo = Repository(session)
            accounts = repo.list_cloud_accounts()

            providers = self._build_providers(accounts)
            zabbix_client = self._build_zabbix_client()

            results = ingestor.ingest_all(providers, zabbix_client)

            self._last_result = results
            self._last_run_time = datetime.now(timezone.utc)
            logger.info("Scheduled ingestion completed: %s", results)
        except Exception as exc:
            self._last_result = {"error": str(exc)}
            self._last_run_time = datetime.now(timezone.utc)
            logger.error("Scheduled ingestion failed: %s", exc)
        finally:
            session.close()

    def _build_providers(self, accounts) -> dict:
        """Build provider instances from cloud accounts and config.

        Returns:
            Dict mapping account ID -> CloudProvider instance.
        """
        from infraverse.providers.yandex import YandexCloudClient
        from infraverse.providers.vcloud import VCloudDirectorClient

        providers = {}
        for account in accounts:
            try:
                if account.provider_type == "yandex_cloud":
                    providers[account.id] = YandexCloudClient(
                        token=self._config.yc_token,
                    )
                elif account.provider_type == "vcloud" and self._config.vcd_configured:
                    providers[account.id] = VCloudDirectorClient(
                        url=self._config.vcd_url,
                        username=self._config.vcd_user,
                        password=self._config.vcd_password,
                        org=account.config.get("org", self._config.vcd_org or "System"),
                    )
            except Exception as exc:
                logger.error("Failed to build provider for account %s: %s", account.name, exc)
        return providers

    def _build_zabbix_client(self):
        """Build a ZabbixClient if configured, otherwise return None."""
        if not self._config.zabbix_configured:
            return None
        try:
            from infraverse.providers.zabbix import ZabbixClient

            return ZabbixClient(
                url=self._config.zabbix_url,
                username=self._config.zabbix_user,
                password=self._config.zabbix_password,
            )
        except Exception as exc:
            logger.error("Failed to build Zabbix client: %s", exc)
            return None
