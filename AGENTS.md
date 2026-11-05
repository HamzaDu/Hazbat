# Hazbat: notes for AI agents

Hazbat is a battery materials traceability database for a scientific group: FastAPI and PostgreSQL, with one Docker
image that either runs its own PostgreSQL (`START_LOCAL_DB=1`) or uses an external one. Users are broadly
trustworthy; the app is meant to sit behind a reverse proxy that handles TLS and CSRF.

## Where code goes
- `main.py` only builds the app: middleware, static files, the router list (alphabetical) and the MCP mount.
- `routers/` the pages and endpoints. One file per feature, each with `router = APIRouter()`.
- `services/` the logic behind them, with no web code (no `Request`, no templates).
- `core/` settings, database connections, login checks, templates.
- `utils/config.py` reads and writes the config file, keeping its comments.
- `templates/`, `static/` the pages and their styling.
- `schemas/` SQL files applied in name order at start-up. While there is no real database, change
  `schemas/0000_schema.sql` directly.
- `scripts/` command-line tools run as modules from `/app` (`python3 -m scripts.name`).
- Render pages with `templates.TemplateResponse(request, "name.html", {...})`.

## Start-up (entrypoint.sh)
Start PostgreSQL if `START_LOCAL_DB` is set, then `initconfig` (adds missing settings to the config file and, for the
built-in database, creates the admin role), `dbgen` (applies the schema, creates the other two roles, grants), the
optional `SEED_SQL` file, then `scripts/serve.py` (uvicorn; `RELOAD` adds `--reload`).

## Configuration
- One INI file, `/etc/hazbat/hazbat.ini`. Do not propose another format.
- `utils/config.py` is the only code that reads or writes the file format. `core/varreg.py` exposes the read-only
  registry `settings`. Never pass a default to `settings.get`: a missing setting is `None`, and defaults are written
  into the file by `scripts/initconfig.py`.
- `[database]`: host, port, name, admin_password, read_write_password, read_only_password.
  `[app]`: base_url, session_secret, two_factor_key, max_2fa_interval_hours, and optionally gemini_api_key and
  trusted_proxies.

## Database
- Three roles: `hazbat_admin` (owns the tables; the only role that touches the user, API key and two-factor tables),
  `hazbat_rw` and `hazbat_ro`. Tables listed in `tbl_unprivileged_tables` are open to the other two roles.
- Use `get_connection(read_only=True)` for reads, `get_connection()` for writes and `get_admin_connection()` for the
  privileged tables.
- Values go in as query parameters. A table or column name may be put into SQL only if it comes from a fixed
  dictionary in the code, never from a request.

## Login and access
- Browser sessions are signed cookies; `core/auth.py` re-reads the user from the database on every request, so a lock
  or a change of role takes effect at once. API clients send `Authorization: Bearer <key>`.
- Every page and endpoint starts with `require_login` (session or key) or `require_session` (browser only). Account
  pages (My Account, API keys, user management) use `require_session`.
- Passwords are stored as bcrypt hashes (`services/account.py`). bcrypt only uses the first 72 bytes, so every place
  that sets a password rejects one longer than 72 bytes.
- Two-factor is TOTP with recovery codes. A signed device cookie skips it for as long as the user's interval (set on
  My Account, capped by `max_2fa_interval_hours`).
- Project access: non-admins see only their projects. Any endpoint that returns records must filter with
  `get_allowed_projects` or check a single record with `record_visible`; creating a record checks `project_visible`.

## MCP interface (routers/mcp_server.py)
- Served at `/mcp/`, API key required. Each tool calls a GET `/api/...` endpoint inside the app with the caller's key,
  so the endpoint's own checks apply.
- Only read-only endpoints become tools. Nothing in `routers/users.py` may ever be exposed.
- All code that touches the MCP library stays in that file. The `mcp` package is pinned exactly in requirements.txt.

## Code style
- Comments and docstrings are short and in the style of the surrounding code.
- No nested comprehensions, and no dense one-line Python where a few plain lines read better.
- Never tell identifiers apart only by case.
- Use inheritance only as a last resort.
- Dependencies in requirements.txt are given as minimum versions and where possible maximum tested versions.

## Needs an explicit instruction from the user
- Any edit to the Dockerfile, to HTML templates, or to CSS or other look and feel.
- Creating new files: ask the user to create an empty one.
- Changing what a function does when the request was only to look at it. If something looks like a bug, say so first.
