"""main.py -- application startup and backend initialization only.

Creates the FastAPI app, configures CORS, and registers api.py's routers.
No route logic, no analysis logic -- see api.py / repository.py /
analyzer.py / ai.py for that.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import (
    ai_router,
    export_router,
    git_router,
    health_analysis_router,
    health_router,
    repository_router,
)
from config import settings

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(repository_router)
app.include_router(ai_router)
app.include_router(git_router)
app.include_router(health_analysis_router)
app.include_router(export_router)
