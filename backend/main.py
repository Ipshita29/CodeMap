from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ai, health, repository, repository_export, repository_git, repository_health
from app.config.settings import settings

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(repository.router)
app.include_router(ai.router)
app.include_router(repository_git.router)
app.include_router(repository_health.router)
app.include_router(repository_export.router)
