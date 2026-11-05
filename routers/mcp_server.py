"""MCP interface: lets an AI client use the read-only API endpoints as tools.

Served at /mcp/ (streamable HTTP). Every request needs an API key in an Authorization: Bearer header.
Each tool calls the matching /api endpoint inside this app with the caller's key, so that endpoint's
login and project checks apply unchanged. Only GET endpoints are exposed.
All the code that touches the MCP library is in this file.
"""

from urllib.parse import quote

import httpx
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.concurrency import run_in_threadpool

from services.cycling import valid_record_id
from services.api import get_api_key_user

main_app = None


def set_main_app(app):
    """Gives the tools the app they call into (called once from main.py)."""
    global main_app
    main_app = app


mcp_server = FastMCP(
    "Hazbat",
    instructions="Read-only access to the Hazbat battery materials traceability database.",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    # Every request is checked for an API key below, so the Host check for unauthenticated local servers is not needed
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def get_json(ctx: Context, path, params=None):
    """GET one of this app's endpoints as the caller and return its JSON.
    Raises ValueError with the endpoint's answer if it refuses."""
    request = ctx.request_context.request
    authorization = ""
    if request is not None:
        authorization = request.headers.get("authorization", "")
    if not authorization:
        raise ValueError("An API key is required.")
    transport = httpx.ASGITransport(app=main_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hazbat") as client:
        response = await client.get(path, params=params, headers={"Authorization": authorization})
    if response.status_code != 200:
        raise ValueError(f"Request failed ({response.status_code}): {response.text}")
    return response.json()


def record_path(prefix, record_id, suffix=""):
    """URL path for an endpoint that takes a record ID. The ID is checked so it cannot reach a different endpoint."""
    if not valid_record_id(record_id):
        raise ValueError("Record IDs only contain letters, numbers and hyphens.")
    return f"{prefix}/{quote(record_id, safe='')}{suffix}"


# --- Records -----------------------------------------------------------------

@mcp_server.tool()
async def get_record_card(record_id: str, ctx: Context) -> dict:
    """Details of one record (material, coating, SLP, coin cell or MLP) and the records linked to it."""
    return await get_json(ctx, record_path("/api/card", record_id))


@mcp_server.tool()
async def get_lineage(record_id: str, ctx: Context) -> dict:
    """Lineage and passport data for one cell (SLP, coin cell or MLP): its materials, coatings, process steps and cycling."""
    return await get_json(ctx, record_path("/api/lineage", record_id))


RECORD_TYPES = ("materials", "coatings", "slp", "coincell", "mlp")


@mcp_server.tool()
async def list_records(record_type: str, ctx: Context, search: str = "", project: str = "",
                       limit: int = 50, offset: int = 0) -> dict:
    """List records of one type: 'materials', 'coatings', 'slp', 'coincell' or 'mlp', sorted by ID.
    search matches part of an ID or text field (chemistry, supplier, made by, electrolyte and so on) ignoring case.
    project limits the list to one project (not for materials). At most 200 rows per call; use offset for the next page."""
    if record_type not in RECORD_TYPES:
        raise ValueError(f"record_type must be one of: {', '.join(RECORD_TYPES)}")
    params = {"limit": limit, "offset": offset}
    if search:
        params["search"] = search
    if project:
        params["project"] = project
    return await get_json(ctx, f"/api/records/{record_type}", params)


# --- Graph -------------------------------------------------------------------

@mcp_server.tool()
async def get_graph(ctx: Context) -> dict:
    """Every record the user can see as graph nodes and links (material, coating, cell, project)."""
    return await get_json(ctx, "/api/graph")


@mcp_server.tool()
async def get_record_graph(record_id: str, ctx: Context) -> dict:
    """One record with the records directly above and below it in the chain, as graph nodes and links."""
    return await get_json(ctx, record_path("/api/graph", record_id))


@mcp_server.tool()
async def get_graph_filters(ctx: Context) -> dict:
    """The values and ranges used to filter the graph: chemistry, supplier, made by, electrolyte, capacity and so on."""
    return await get_json(ctx, "/api/filters")


# --- Charts ------------------------------------------------------------------

@mcp_server.tool()
async def chart_formation_capacity(ctx: Context) -> dict:
    """Formation capacity of each SLP cell."""
    return await get_json(ctx, "/api/chart/formation-capacity")


@mcp_server.tool()
async def chart_my_projects(ctx: Context) -> dict:
    """Number of coatings and cells in each project the user can see."""
    return await get_json(ctx, "/api/chart/my-projects")


@mcp_server.tool()
async def chart_gsm_by_coating(ctx: Context) -> dict:
    """Coat weight (g/m²) of each coating."""
    return await get_json(ctx, "/api/chart/gsm-by-coating")


@mcp_server.tool()
async def chart_records_per_table(ctx: Context) -> dict:
    """How many records of each type the user can see."""
    return await get_json(ctx, "/api/chart/records-per-table")


@mcp_server.tool()
async def chart_coatings_over_time(ctx: Context) -> dict:
    """Number of coatings made on each date."""
    return await get_json(ctx, "/api/chart/coatings-over-time")


# --- Cycling data ------------------------------------------------------------

@mcp_server.tool()
async def get_cycling_summary(record_id: str, ctx: Context) -> dict:
    """Capacity per half-cycle, coulombic efficiency and state of health from a record's latest cycling file."""
    return await get_json(ctx, record_path("/api/cycling", record_id, "/summary"))


@mcp_server.tool()
async def get_cycling_curves(record_id: str, ctx: Context, cycles: str = "1,2") -> dict:
    """Voltage against capacity for chosen full cycles: numbers such as '1,2', 'last', or 'all' (at most 20)."""
    return await get_json(ctx, record_path("/api/cycling", record_id, "/curves"), {"cycles": cycles})


@mcp_server.tool()
async def get_cycling_half_cycle(record_id: str, half_cycle: int, ctx: Context) -> dict:
    """Voltage against capacity for one half-cycle of a record's latest cycling file."""
    return await get_json(ctx, record_path("/api/cycling", record_id, f"/cycle/{half_cycle}"))


# --- Access control ----------------------------------------------------------

class RequireApiKey:
    """Wraps the MCP app and refuses any request without a valid API key before the app sees it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            authorization = headers.get(b"authorization", b"").decode()
            user = None
            if authorization.lower().startswith("bearer "):
                user = await run_in_threadpool(get_api_key_user, authorization[7:].strip())
            if not user:
                response = JSONResponse({"error": "Invalid or missing API key"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# The session manager only exists once the app has been built; main.py runs it for the life of the server
mcp_http_app = mcp_server.streamable_http_app()
mcp_app = RequireApiKey(mcp_http_app)
