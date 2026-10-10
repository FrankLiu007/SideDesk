from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.catalog import ensure_catalog
from app.database import SessionLocal, init_db
from app.jobs import import_seed_file
from app.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with SessionLocal() as session:
        ensure_catalog(session)
        import_seed_file(session)
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="SideDesk", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5175", "http://localhost:5175"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
