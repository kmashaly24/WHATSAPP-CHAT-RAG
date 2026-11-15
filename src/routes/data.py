from fastapi import FastAPI, APIRouter, Depends, UploadFile, status, Request
from fastapi.responses import JSONResponse
import os
from helpers.config import get_settings, Settings
from controllers import DataController, ProjectController, ProcessFactory
import aiofiles
from models import ResponseSignal
import logging
from .schemes.data import ProcessRequest
from models.db_schemes import DataChunk, Asset
from models.enums.AssetTypeEnum import AssetTypeEnum

logger = logging.getLogger('uvicorn.error')

data_router = APIRouter(
    prefix="/api/v1/data",
    tags=["api_v1", "data"],
)

@data_router.post("/upload/{project_id}")
async def upload_data(request: Request, project_id: int, file: UploadFile,
                      app_settings: Settings = Depends(get_settings)):

    logger.info(f"Upload started: project_id={project_id} filename={file.filename} content_type={file.content_type}")

    project_model = request.app.project_model

    project = await project_model.get_project_or_create_one(
        project_id=project_id
    )

    # validate the file properties
    data_controller = DataController()

    is_valid, result_signal = data_controller.validate_uploaded_file(file=file)

    if not is_valid:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": result_signal
            }
        )

    project_dir_path = ProjectController().get_project_path(project_id=project_id)
    file_path, file_id = data_controller.generate_unique_filepath(
        orig_file_name=file.filename,
        project_id=project_id
    )

    try:
        async with aiofiles.open(file_path, "wb") as f:
            while chunk := await file.read(app_settings.FILE_DEFAULT_CHUNK_SIZE):
                await f.write(chunk)
    except Exception as e:

        logger.error(f"Error while uploading file: {e}")

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.FILE_UPLOAD_FAILED.value
            }
        )

    # store the assets into the database
    asset_model = request.app.asset_model

    asset_resource = Asset(
        asset_project_id=project.project_id,
        asset_type=AssetTypeEnum.ZIP.value,
        asset_name=file_id,
        asset_size=os.path.getsize(file_path)
    )

    asset_record = await asset_model.create_asset(asset=asset_resource)

    logger.info(
        f"Upload finished: project_id={project.project_id} file_id={asset_record.asset_id} asset_name={file_id}"
    )

    return JSONResponse(
            content={
                "signal": ResponseSignal.FILE_UPLOAD_SUCCESS.value,
                "file_id": str(asset_record.asset_id),
            }
        )

@data_router.post("/process/{project_id}")
async def process_endpoint(request: Request, project_id: int, process_request: ProcessRequest):

    chunk_size = process_request.chunk_size
    overlap_size = process_request.overlap_size
    do_reset = process_request.do_reset
    file_type = (process_request.type or "all").lower()

    if file_type not in {"all", "chat", "record", "document"}:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.FILE_TYPE_NOT_SUPPORTED.value,
            }
        )

    logger.info(
        f"Process started: project_id={project_id} file_id={process_request.file_id} "
        f"chunk_size={chunk_size} overlap_size={overlap_size} do_reset={do_reset} type={file_type}"
    )

    project_model = request.app.project_model
    nlp_controller = request.app.nlp_controller
    asset_model = request.app.asset_model
    chunk_model = request.app.chunk_model

    project = await project_model.get_project_or_create_one(
        project_id=project_id
    )

    project_files_ids = {}
    if process_request.file_id:
        asset_record = await asset_model.get_asset_record(
            asset_project_id=project.project_id,
            asset_name=process_request.file_id
        )

        if asset_record is None or asset_record.asset_parent_id is not None or asset_record.asset_type != AssetTypeEnum.ZIP.value:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.FILE_ID_ERROR.value,
                }
            )

        project_files_ids = {
            asset_record.asset_id: asset_record.asset_name
        }

    else:
        project_files = await asset_model.get_uploaded_assets(
            asset_project_id=project.project_id,
        )

        project_files_ids = {
            record.asset_id: record.asset_name
            for record in project_files
        }

    if len(project_files_ids) == 0:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.NO_FILES_ERROR.value,
            }
        )
    
    process_controller = ProcessFactory(
        project_id=project_id,
        stt_client=request.app.stt_client,
    )

    no_records = 0
    no_files = 0

    if do_reset == 1:
        # delete associated vectors collection
        collection_name = nlp_controller.create_collection_name(project_id=project.project_id)
        _ = await request.app.vectordb_client.delete_collection(collection_name=collection_name)

        # delete associated chunks
        _ = await chunk_model.delete_chunks_by_project_id(
            project_id=project.project_id
        )

        _ = await asset_model.delete_child_assets_by_project_id(
            project_id=project.project_id
        )

    for asset_id, file_id in project_files_ids.items():

        logger.info(f"Processing asset_id={asset_id} file_id={file_id} project_id={project.project_id}")

        processed_files = await process_controller.process_file(
            file_id=file_id,
            chunk_size=chunk_size,
            overlap_size=overlap_size,
            file_type=file_type,
        )

        if not processed_files:
            logger.error(f"No supported files processed from file_id={file_id}")
            continue

        for processed_file in processed_files:
            child_asset = await asset_model.create_asset(Asset(
                asset_project_id=project.project_id,
                asset_type=processed_file.asset_type,
                asset_name=processed_file.stored_name,
                asset_size=processed_file.size,
                asset_parent_id=asset_id,
            ))
            chunk_asset_id = child_asset.asset_id
            logger.info(
                f"Created child asset_id={chunk_asset_id} parent_asset_id={asset_id} name={processed_file.original_name}"
            )

            file_chunks_records = [
                DataChunk(
                    chunk_text=chunk.page_content,
                    chunk_metadata=chunk.metadata,
                    chunk_order=i+1,
                    chunk_project_id=project.project_id,
                    chunk_asset_id=chunk_asset_id,
                )
                for i, chunk in enumerate(processed_file.chunks)
                if chunk.page_content and chunk.page_content.strip()
            ]

            if len(file_chunks_records) == 0:
                logger.info(f"No text chunks produced for {processed_file.original_name}")
                continue

            no_records += await chunk_model.insert_many_chunks(chunks=file_chunks_records)
            no_files += 1
            logger.info(
                f"Processed {processed_file.original_name} chunks={len(file_chunks_records)} asset_id={chunk_asset_id}"
            )

    if no_files == 0:
        logger.error(f"No supported files processed for project_id={project.project_id}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.PROCESSING_FAILED.value
            }
        )

    logger.info(
        f"Process finished: project_id={project.project_id} inserted_chunks={no_records} processed_files={no_files}"
    )

    return JSONResponse(
        content={
            "signal": ResponseSignal.PROCESSING_SUCCESS.value,
            "inserted_chunks": no_records,
            "processed_files": no_files
        }
    )

@data_router.delete("/{project_id}")
async def delete_project_data(request: Request, project_id: int):

    logger.info(f"Delete started: project_id={project_id}")

    project_model = request.app.project_model

    project = await project_model.get_project(
        project_id=project_id
    )

    if project is None:
        logger.error(f"Project not found for deletion: project_id={project_id}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.PROJECT_NOT_FOUND_ERROR.value
            }
        )

    try:
        nlp_controller = request.app.nlp_controller
        chunk_model = request.app.chunk_model
        asset_model = request.app.asset_model

        deleted_vectors = await nlp_controller.reset_vector_db_collection(project=project)
        logger.info(f"Vector collection deleted for project_id={project.project_id}: {deleted_vectors}")

        deleted_chunks = await chunk_model.delete_chunks_by_project_id(
            project_id=project.project_id
        )
        logger.info(f"Deleted chunks={deleted_chunks} for project_id={project.project_id}")

        deleted_assets = await asset_model.delete_assets_by_project_id(
            project_id=project.project_id
        )
        logger.info(f"Deleted assets={deleted_assets} for project_id={project.project_id}")

        deleted_project = await project_model.delete_project_by_id(
            project_id=project.project_id
        )
        logger.info(f"Deleted project row={deleted_project} for project_id={project.project_id}")

        files_deleted = ProjectController().delete_project_files(project_id=project_id)
        logger.info(f"Project files removed={files_deleted} for project_id={project_id}")

    except Exception as e:
        logger.error(f"Error while deleting project_id={project_id}: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.PROJECT_DELETE_ERROR.value
            }
        )

    logger.info(f"Delete finished: project_id={project_id}")

    return JSONResponse(
        content={
            "signal": ResponseSignal.PROJECT_DELETE_SUCCESS.value,
            "deleted_chunks": deleted_chunks,
            "deleted_assets": deleted_assets,
        }
    )
