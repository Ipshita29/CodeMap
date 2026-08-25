"""main.py -- application startup and backend initialization only.

Creates the FastAPI app, configures logging and CORS, and registers
api.py's routers. No route logic, no analysis logic -- see api.py /
repository.py / analyzer.py / ai.py for that.
"""

import logging

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

# The ONE place logging is configured -- every other module just does
# `logger = logging.getLogger(__name__)` and relies on this. Configuring it
# here, before the app is constructed, means it's in effect for every log
# call any route/service makes; module names line up with the file that
# emitted the line (repository.py's logger is named "repository", etc.),
# so e.g. "... | ERROR | ai | AI provider timeout ..." tells you exactly
# which file to look in. Level is controlled by LOG_LEVEL in .env.
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

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
