# Contributing to Hazbat

## Where code lives

```
main.py        builds the app and includes the routers. Nothing else goes here.
core/          used everywhere: settings, database connection, templates, login checks
services/      logic with no web code: database lookups, calculations, file parsing
routers/       pages and API endpoints, one file per feature
templates/     HTML pages (Jinja2)
static/        CSS, JavaScript, images
tests/         smoke test
schema.sql     database tables
```

| Router | Pages | Logic in |
|---|---|---|
| `routers/home.py` | `/` | |
| `routers/auth.py` | login, logout, add user | |
| `routers/records.py` | new material / coating / SLP / coin cell / MLP forms | `services/forms.py` |
| `routers/records_edit.py` | edit and delete forms | |
| `routers/bulk_upload.py` | bulk upload pages | `services/bulk.py` |
| `routers/inventory.py` | directory search, inventory tables, CSV/Excel export | |
| `routers/cards.py` | `/card`, `/api/card`, `/qr` | `services/cards.py` |
| `routers/lineage.py` | lineage & passport page and JSON | `services/lineage.py` |
| `routers/cycling.py` | .mpr upload, summary, voltage curves | `services/cycling.py` |
| `routers/graph.py` | traceability graph and filters | |
| `routers/charts.py` | `/chart` and `/api/chart/*` | |
| `routers/hazbot.py` | HAZbot page and ask endpoint | `HAZbot.py` |

## Adding something new

- **A page or endpoint for an existing feature:** add it to that feature's router file.
- **A new feature:** create `routers/<feature>.py` with `router = APIRouter()`, then add the module to the
  list in `main.py`.
- **Database queries or calculations** that more than one page needs, or that are long: put them in
  `services/`, as plain functions that take values (not the `Request`) and return data.
- **Settings:** read them in `core/config.py` from an environment variable, never hard-code them.

Rules of thumb:
- Routers read the request, check the login, call a service, and return a page or JSON.
- Services never import from `routers/`.
- Use `%s` placeholders for every value in SQL. Only put table or column names into SQL text when they
  come from our own code.
- Give each new function a one-line docstring saying what it does, and comment the *why* of anything
  non-obvious.

## Before opening a pull request
1. Run pre-commit checks. Some issues are fixed automatically. Fix any issues flagged that were not fixed automatically.
   ```bash
   pip install -r requirements-dev.txt
   pre-commit run --all-files
   ```

2. Run the smoke test against your dev database:
   ```bash
   pip install -r requirements-dev.txt
   pytest -q
   ```
2. If you changed the database tables, update `schema.sql` and write down the `ALTER TABLE` you ran.
3. Keep each pull request to one change, and describe what you tested.
