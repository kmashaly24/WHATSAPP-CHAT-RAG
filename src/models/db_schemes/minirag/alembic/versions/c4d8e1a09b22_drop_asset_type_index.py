"""drop asset type index

Revision ID: c4d8e1a09b22
Revises: b7e2a91c0d44
Create Date: 2026-11-14 18:50:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c4d8e1a09b22"
down_revision: Union[str, None] = "b7e2a91c0d44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_asset_type", table_name="assets")


def downgrade() -> None:
    op.create_index("ix_asset_type", "assets", ["asset_type"], unique=False)
