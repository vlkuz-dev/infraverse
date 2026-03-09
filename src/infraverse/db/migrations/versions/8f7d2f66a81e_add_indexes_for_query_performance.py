"""add indexes for query performance

Revision ID: 8f7d2f66a81e
Revises: 8be05b9a34da
Create Date: 2026-03-09 08:37:02.200250

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8f7d2f66a81e'
down_revision: Union[str, Sequence[str], None] = '8be05b9a34da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All indexes added by this migration.
_INDEXES = [
    ("cloud_accounts", "ix_cloud_accounts_tenant_id", ["tenant_id"]),
    ("monitoring_hosts", "ix_monitoring_hosts_cloud_account_id", ["cloud_account_id"]),
    ("monitoring_hosts", "ix_monitoring_hosts_name", ["name"]),
    ("netbox_hosts", "ix_netbox_hosts_tenant_id", ["tenant_id"]),
    ("sync_runs", "ix_sync_runs_account_started", ["cloud_account_id", "started_at"]),
    ("sync_runs", "ix_sync_runs_source", ["source"]),
    ("vms", "ix_vms_cloud_account_id", ["cloud_account_id"]),
    ("vms", "ix_vms_name", ["name"]),
    ("vms", "ix_vms_status", ["status"]),
]


def upgrade() -> None:
    """Upgrade schema."""
    # Guard against indexes already created by Base.metadata.create_all().
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes: dict[str, set[str]] = {}
    for table, idx_name, _ in _INDEXES:
        if table not in existing_indexes:
            existing_indexes[table] = {
                idx["name"] for idx in inspector.get_indexes(table)
            }

    for table, idx_name, columns in _INDEXES:
        if idx_name not in existing_indexes.get(table, set()):
            op.create_index(idx_name, table, columns)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes: dict[str, set[str]] = {}
    for table, idx_name, _ in _INDEXES:
        if table not in existing_indexes:
            existing_indexes[table] = {
                idx["name"] for idx in inspector.get_indexes(table)
            }

    for table, idx_name, _ in reversed(_INDEXES):
        if idx_name in existing_indexes.get(table, set()):
            op.drop_index(idx_name, table_name=table)
