from fastapi import FastAPI
from routes import base, data, nlp
from helpers.config import get_settings
from stores.llm.LLMProviderFactory import LLMProviderFactory
from stores.vectordb.PGVectorDB import PGVectorDB
from stores.stt.STTProviderFactory import STTProviderFactory
from stores.llm.templates.template_parser import TemplateParser
from models.ProjectModel import ProjectModel
from models.ChunkModel import ChunkModel
from models.AssetModel import AssetModel
from controllers import NLPController
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import logging

# Import metrics setup
from utils.metrics import setup_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI()

# Setup Prometheus metrics
setup_metrics(app)

async def startup_span():
    settings = get_settings()
    logger = logging.getLogger("uvicorn.error")
    logger.info(
        f"Starting {settings.APP_NAME} v{settings.APP_VERSION} "
        f"generation={settings.GENERATION_BACKEND} embedding={settings.EMBEDDING_BACKEND} "
        f"lang={settings.PRIMARY_LANG} speech={settings.SPEECH_BACKEND}"
    )

    postgres_conn = f"postgresql+asyncpg://{settings.POSTGRES_USERNAME}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_MAIN_DATABASE}"

    app.db_engine = create_async_engine(postgres_conn)
    app.db_client = sessionmaker(
        app.db_engine, class_=AsyncSession, expire_on_commit=False
    )

    llm_provider_factory = LLMProviderFactory(settings)

    # generation client
    app.generation_client = llm_provider_factory.create(provider=settings.GENERATION_BACKEND)
    app.generation_client.set_generation_model(model_id = settings.GENERATION_MODEL_ID)

    # embedding client
    app.embedding_client = llm_provider_factory.create(provider=settings.EMBEDDING_BACKEND)
    app.embedding_client.set_embedding_model(model_id=settings.EMBEDDING_MODEL_ID,
                                             embedding_size=settings.EMBEDDING_MODEL_SIZE)
    
    # vector db client
    app.vectordb_client = PGVectorDB(
        db_client=app.db_client,
        default_vector_size=settings.EMBEDDING_MODEL_SIZE,
    )
    await app.vectordb_client.connect()

    stt_provider_factory = STTProviderFactory(settings)
    app.stt_client = stt_provider_factory.create(provider=settings.SPEECH_BACKEND)

    app.template_parser = TemplateParser(
        language=settings.PRIMARY_LANG,
        default_language=settings.DEFAULT_LANG,
    )

    app.project_model = ProjectModel(db_client=app.db_client)
    app.chunk_model = ChunkModel(db_client=app.db_client)
    app.asset_model = AssetModel(db_client=app.db_client)
    app.nlp_controller = NLPController(
        vectordb_client=app.vectordb_client,
        generation_client=app.generation_client,
        embedding_client=app.embedding_client,
        template_parser=app.template_parser,
    )


async def shutdown_span():
    app.db_engine.dispose()
    await app.vectordb_client.disconnect()

app.on_event("startup")(startup_span)
app.on_event("shutdown")(shutdown_span)

app.include_router(base.base_router)
app.include_router(data.data_router)
app.include_router(nlp.nlp_router)
