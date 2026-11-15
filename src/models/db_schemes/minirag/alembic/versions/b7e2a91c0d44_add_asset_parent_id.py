"""add optional parent asset id

Revision ID: b7e2a91c0d44
Revises: fee4cd54bd38
Create Date: 2026-11-08 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e2a91c0d44"
down_revision: Union[str, None] = "fee4cd54bd38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("asset_parent_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_assets_asset_parent_id",
        "assets",
        "assets",
        ["asset_parent_id"],
        ["asset_id"],
    )
    op.create_index("ix_asset_parent_id", "assets", ["asset_parent_id"])


def downgrade() -> None:
    op.drop_index("ix_asset_parent_id", table_name="assets")
    op.drop_constraint("fk_assets_asset_parent_id", "assets", type_="foreignkey")
    op.drop_column("assets", "asset_parent_id")
