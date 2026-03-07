"""Configuration module for Infraverse."""

import os
import logging


def setup_logging() -> None:
    """Configure logging from LOG_LEVEL env var."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for name in ("urllib3", "requests", "httpx", "httpcore", "pynetbox"):
        logging.getLogger(name).setLevel(logging.WARNING)


class Config:
    """Application configuration."""

    def __init__(
        self,
        yc_token: str,
        netbox_url: str,
        netbox_token: str,
        dry_run: bool = False,
        database_url: str = "sqlite:///infraverse.db",
        vcd_url: str | None = None,
        vcd_user: str | None = None,
        vcd_password: str | None = None,
        vcd_org: str | None = None,
        zabbix_url: str | None = None,
        zabbix_user: str | None = None,
        zabbix_password: str | None = None,
        sync_interval_minutes: int = 0,
        yc_console_url: str | None = None,
        zabbix_host_url: str | None = None,
        netbox_vm_url: str | None = None,
        yc_sa_key_file: str | None = None,
    ):
        self.yc_token = yc_token
        self.yc_sa_key_file = yc_sa_key_file
        self.netbox_url = netbox_url
        self.netbox_token = netbox_token
        self.dry_run = dry_run
        self.database_url = database_url
        self.vcd_url = vcd_url
        self.vcd_user = vcd_user
        self.vcd_password = vcd_password
        self.vcd_org = vcd_org
        self.zabbix_url = zabbix_url
        self.zabbix_user = zabbix_user
        self.zabbix_password = zabbix_password
        self.sync_interval_minutes = sync_interval_minutes
        self.yc_console_url = yc_console_url
        self.zabbix_host_url = zabbix_host_url
        self.netbox_vm_url = netbox_vm_url

    @classmethod
    def from_env(cls, dry_run: bool = False) -> "Config":
        """Create configuration from environment variables.

        Raises:
            ValueError: If required environment variables are missing.
        """
        yc_sa_key_file = os.getenv("YC_SA_KEY_FILE") or None
        yc_token = os.getenv("YC_TOKEN")
        netbox_url = os.getenv("NETBOX_URL")
        netbox_token = os.getenv("NETBOX_TOKEN")

        missing = []
        if not yc_token and not yc_sa_key_file:
            missing.append("YC_TOKEN")
        if not netbox_url:
            missing.append("NETBOX_URL")
        if not netbox_token:
            missing.append("NETBOX_TOKEN")

        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Please set them in your environment or .env file."
            )

        return cls(
            yc_token=yc_token or "",
            netbox_url=netbox_url,
            netbox_token=netbox_token,
            dry_run=dry_run,
            database_url=os.getenv("DATABASE_URL", "sqlite:///infraverse.db"),
            vcd_url=os.getenv("VCD_URL") or None,
            vcd_user=os.getenv("VCD_USER") or None,
            vcd_password=os.getenv("VCD_PASSWORD") or None,
            vcd_org=os.getenv("VCD_ORG") or None,
            zabbix_url=os.getenv("ZABBIX_URL") or None,
            zabbix_user=os.getenv("ZABBIX_USER") or None,
            zabbix_password=os.getenv("ZABBIX_PASSWORD") or None,
            sync_interval_minutes=cls._parse_sync_interval(),
            yc_console_url=os.getenv("YC_CONSOLE_URL") or None,
            zabbix_host_url=os.getenv("ZABBIX_HOST_URL") or None,
            netbox_vm_url=os.getenv("NETBOX_VM_URL") or None,
            yc_sa_key_file=yc_sa_key_file,
        )

    @classmethod
    def _parse_sync_interval(cls) -> int:
        raw = os.getenv("SYNC_INTERVAL_MINUTES", "0")
        try:
            value = int(raw)
        except ValueError:
            logging.getLogger(__name__).warning(
                "Invalid SYNC_INTERVAL_MINUTES=%r, defaulting to 0 (disabled)", raw
            )
            return 0
        if value < 0:
            logging.getLogger(__name__).warning(
                "Negative SYNC_INTERVAL_MINUTES=%d, defaulting to 0 (disabled)", value
            )
            return 0
        return value

    @property
    def vcd_configured(self) -> bool:
        """Return True if vCloud Director credentials are fully configured."""
        return all([self.vcd_url, self.vcd_user, self.vcd_password])

    @property
    def zabbix_configured(self) -> bool:
        """Return True if Zabbix credentials are fully configured."""
        return all([self.zabbix_url, self.zabbix_user, self.zabbix_password])

    def setup_logging(self) -> None:
        """Configure logging for the application."""
        setup_logging()

    def __repr__(self) -> str:
        """Return string representation with masked tokens."""
        def _mask(value: str) -> str:
            if len(value) <= 12:
                return "***"
            return value[:4] + "***" + value[-4:]

        return (
            f"Config(netbox_url={self.netbox_url!r}, "
            f"yc_token={_mask(self.yc_token)!r}, "
            f"netbox_token={_mask(self.netbox_token)!r}, "
            f"vcd_password={'***' if self.vcd_password else None}, "
            f"zabbix_password={'***' if self.zabbix_password else None}, "
            f"dry_run={self.dry_run})"
        )
