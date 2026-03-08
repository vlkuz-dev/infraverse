"""initial_schema

Revision ID: 8be05b9a34da
Revises: 
Create Date: 2026-03-09 00:05:02.339801

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8be05b9a34da'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Guard against tables already created by Base.metadata.create_all() (e.g.
    # web app startup or legacy code paths).  This makes "upgrade head" safe
    # regardless of whether init_db() ran first.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if 'tenants' not in existing:
        op.create_table('tenants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
        )
    if 'cloud_accounts' not in existing:
        op.create_table('cloud_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('provider_type', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if 'netbox_hosts' not in existing:
        op.create_table('netbox_hosts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('ip_addresses', sa.JSON(), nullable=True),
        sa.Column('cluster_name', sa.String(), nullable=True),
        sa.Column('vcpus', sa.Integer(), nullable=True),
        sa.Column('memory_mb', sa.Integer(), nullable=True),
        sa.Column('tenant_id', sa.Integer(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('external_id')
        )
    if 'monitoring_hosts' not in existing:
        op.create_table('monitoring_hosts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('ip_addresses', sa.JSON(), nullable=True),
        sa.Column('cloud_account_id', sa.Integer(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['cloud_account_id'], ['cloud_accounts.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source', 'external_id', name='uq_monitoring_source_external')
        )
    if 'sync_runs' not in existing:
        op.create_table('sync_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cloud_account_id', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('items_found', sa.Integer(), nullable=True),
        sa.Column('items_created', sa.Integer(), nullable=True),
        sa.Column('items_updated', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['cloud_account_id'], ['cloud_accounts.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if 'vms' not in existing:
        op.create_table('vms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cloud_account_id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('ip_addresses', sa.JSON(), nullable=True),
        sa.Column('vcpus', sa.Integer(), nullable=True),
        sa.Column('memory_mb', sa.Integer(), nullable=True),
        sa.Column('cloud_name', sa.String(), nullable=True),
        sa.Column('folder_name', sa.String(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        sa.Column('last_sync_error', sa.String(), nullable=True),
        sa.Column('monitoring_exempt', sa.Boolean(), nullable=False),
        sa.Column('monitoring_exempt_reason', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['cloud_account_id'], ['cloud_accounts.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cloud_account_id', 'external_id', name='uq_vm_account_external')
        )


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('vms')
    op.drop_table('sync_runs')
    op.drop_table('monitoring_hosts')
    op.drop_table('netbox_hosts')
    op.drop_table('cloud_accounts')
    op.drop_table('tenants')
    # ### end Alembic commands ###
