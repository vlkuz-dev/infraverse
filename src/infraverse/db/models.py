"""SQLAlchemy ORM models for Infraverse."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Index,
    Integer,
    String,
    DateTime,
    ForeignKey,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    cloud_accounts = relationship(
        "CloudAccount", back_populates="tenant", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Tenant(id={self.id}, name={self.name!r})>"


class CloudAccount(Base):
    __tablename__ = "cloud_accounts"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    provider_type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="cloud_accounts")
    vms = relationship(
        "VM", back_populates="cloud_account", cascade="all, delete-orphan"
    )
    sync_runs = relationship(
        "SyncRun", back_populates="cloud_account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_cloud_accounts_tenant_id", "tenant_id"),
    )

    def __repr__(self):
        return f"<CloudAccount(id={self.id}, name={self.name!r}, provider={self.provider_type!r})>"


class VM(Base):
    __tablename__ = "vms"

    id = Column(Integer, primary_key=True)
    cloud_account_id = Column(Integer, ForeignKey("cloud_accounts.id"), nullable=False)
    external_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="unknown")
    ip_addresses = Column(JSON, default=list)
    vcpus = Column(Integer, nullable=True)
    memory_mb = Column(Integer, nullable=True)
    cloud_name = Column(String, nullable=True)
    folder_name = Column(String, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    last_sync_error = Column(String, nullable=True)
    monitoring_exempt = Column(Boolean, default=False, nullable=False)
    monitoring_exempt_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    cloud_account = relationship("CloudAccount", back_populates="vms")

    __table_args__ = (
        UniqueConstraint("cloud_account_id", "external_id", name="uq_vm_account_external"),
        Index("ix_vms_cloud_account_id", "cloud_account_id"),
        Index("ix_vms_status", "status"),
        Index("ix_vms_name", "name"),
    )

    def __repr__(self):
        return f"<VM(id={self.id}, name={self.name!r}, status={self.status!r})>"


class MonitoringHost(Base):
    __tablename__ = "monitoring_hosts"

    id = Column(Integer, primary_key=True)
    source = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="unknown")
    ip_addresses = Column(JSON, default=list)
    cloud_account_id = Column(
        Integer, ForeignKey("cloud_accounts.id"), nullable=True
    )
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    cloud_account = relationship("CloudAccount")

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_monitoring_source_external"),
        Index("ix_monitoring_hosts_cloud_account_id", "cloud_account_id"),
        Index("ix_monitoring_hosts_name", "name"),
    )

    def __repr__(self):
        return f"<MonitoringHost(id={self.id}, name={self.name!r}, source={self.source!r})>"


class NetBoxHost(Base):
    __tablename__ = "netbox_hosts"

    id = Column(Integer, primary_key=True)
    external_id = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="unknown")
    ip_addresses = Column(JSON, default=list)
    cluster_name = Column(String, nullable=True)
    vcpus = Column(Integer, nullable=True)
    memory_mb = Column(Integer, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    tenant = relationship("Tenant")

    __table_args__ = (
        Index("ix_netbox_hosts_tenant_id", "tenant_id"),
    )

    def __repr__(self):
        return f"<NetBoxHost(id={self.id}, name={self.name!r}, external_id={self.external_id!r})>"


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id = Column(Integer, primary_key=True)
    cloud_account_id = Column(Integer, ForeignKey("cloud_accounts.id"), nullable=True)
    source = Column(String, nullable=False)
    started_at = Column(DateTime, default=_utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="running")
    items_found = Column(Integer, default=0)
    items_created = Column(Integer, default=0)
    items_updated = Column(Integer, default=0)
    error_message = Column(String, nullable=True)

    cloud_account = relationship("CloudAccount", back_populates="sync_runs")

    __table_args__ = (
        Index("ix_sync_runs_source", "source"),
        Index("ix_sync_runs_account_started", "cloud_account_id", "started_at"),
    )

    def __repr__(self):
        return f"<SyncRun(id={self.id}, source={self.source!r}, status={self.status!r})>"
