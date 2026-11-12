"""Hazbat / BMAC traceability database: the web app's entry point.

Start it with:  uvicorn main:app --reload

This file only builds the app. Each feature lives in its own file:
  routers/   the pages and API endpoints (what the browser asks for)
  services/  the logic behind them (database lookups, file parsing)
  core/      settings, database connection, templates and login checks
See CONTRIBUTING.md for where to put new code.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from core.config import SESSION_SECRET
from routers import (
    api_keys,
    auth,
    bulk_upload,
    cards,
    charts,
    coa,
    cycling,
    graph,
    hazbot,
    home,
    inventory,
    lineage,
    projects,
    records,
    records_edit,
    synthesis,
    two_factor,
    users,
)
from routers.mcp_server import mcp_app, mcp_server, set_main_app


@asynccontextmanager
async def lifespan(app):
    """Runs the MCP session manager for as long as the server is up."""
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Add every router's pages to the app. The order does not matter: no two URLs overlap.
for module in (
    api_keys,
    auth,
    bulk_upload,
    cards,
    charts,
    coa,
    cycling,
    graph,
    hazbot,
    home,
    inventory,
    lineage,
    projects,
    records,
    records_edit,
    synthesis,
    two_factor,
    users,
):
    app.include_router(module.router)

# The MCP interface (routers/mcp_server.py): its tools call back into this app
set_main_app(app)
app.mount("/mcp", mcp_app)
