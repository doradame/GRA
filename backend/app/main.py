import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, Base, engine
from app.routers import auth, documents, chat, graph, kb, logs, admin
from app.services.sparse_corpus_stats import reconcile_bm25_cache_if_needed

settings = get_settings()
logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:
        # Dev convenience only. Production should run Alembic migrations.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    if settings.reconcile_bm25_on_startup:
        # Auto-ripara la cache BM25 Redis da Postgres se mancante/out-of-sync: senza di
        # questo, un flush Redis renderebbe il retrieval sparso silenziosamente inerte.
        # Fault-tolerant: un fallimento (Redis/DB non pronti, demo mode) non blocca lo startup.
        try:
            async with AsyncSessionLocal() as db:
                await reconcile_bm25_cache_if_needed(db, settings.reconcile_bm25_tolerance)
        except Exception:
            logger.warning("Reconcile cache BM25 allo startup saltato", exc_info=True)
    yield
    await engine.dispose()


app = FastAPI(
    title="Graph RAG Assistant API",
    description="Generic Graph RAG backend for querying document-based knowledge bases.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_admin_url, "http://localhost:3080"],  # admin + LibreChat
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
app.include_router(graph.router, prefix="/api/v1/graph", tags=["Graph"])
app.include_router(kb.router, prefix="/api/v1/kb", tags=["Knowledge Base"])
app.include_router(logs.router, prefix="/api/v1/logs", tags=["Logs"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])


@app.get("/health")
async def health():
    return {"status": "ok"}
