from .BaseDataModel import BaseDataModel
from .db_schemes import Asset
from .enums.AssetTypeEnum import AssetTypeEnum
from sqlalchemy.future import select
from sqlalchemy import delete

class AssetModel(BaseDataModel):

    def __init__(self, db_client: object):
        super().__init__(db_client=db_client)
        self.db_client = db_client

    async def create_asset(self, asset: Asset):

        async with self.db_client() as session:
            async with session.begin():
                session.add(asset)
            await session.commit()
            await session.refresh(asset)
        return asset

    async def get_uploaded_assets(self, asset_project_id: int):

        async with self.db_client() as session:
            stmt = select(Asset).where(
                Asset.asset_project_id == asset_project_id,
                Asset.asset_parent_id.is_(None),
                Asset.asset_type == AssetTypeEnum.ZIP.value,
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
        return records

    async def get_all_project_assets(self, asset_project_id: str, asset_type: str):

        async with self.db_client() as session:
            stmt = select(Asset).where(
                Asset.asset_project_id == asset_project_id,
                Asset.asset_type == asset_type
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
        return records

    async def get_asset_record(self, asset_project_id: str, asset_name: str):

        async with self.db_client() as session:
            stmt = select(Asset).where(
                Asset.asset_project_id == asset_project_id,
                Asset.asset_name == asset_name
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
        return record

    async def delete_child_assets_by_project_id(self, project_id: int):

        async with self.db_client() as session:
            stmt = delete(Asset).where(
                Asset.asset_project_id == project_id,
                Asset.asset_parent_id.is_not(None),
            )
            result = await session.execute(stmt)
            await session.commit()
        return result.rowcount

    async def delete_assets_by_project_id(self, project_id: int):

        async with self.db_client() as session:
            children = delete(Asset).where(
                Asset.asset_project_id == project_id,
                Asset.asset_parent_id.is_not(None),
            )
            parents = delete(Asset).where(Asset.asset_project_id == project_id)
            child_result = await session.execute(children)
            parent_result = await session.execute(parents)
            await session.commit()
        return child_result.rowcount + parent_result.rowcount


    
