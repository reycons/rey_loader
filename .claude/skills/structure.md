---
name: structure
description: Project structure, architecture, and configuration standards
---

# Project Structure & Architecture

## Python Project Layout

Every Python project must follow this structure:

```
project_root/
├── main.py                     # Orchestration only — no business logic
├── config/
│   ├── config.dev.yaml         # Dev environment config
│   ├── config.prod.yaml        # Prod environment config
│   ├── db/                     # Database connection configs
│   │   └── postgres.yaml
│   ├── data_feeds/             # Data source configs
│   │   └── api_sources.yaml
│   └── app/                    # App-specific config
│       └── rules.yaml
├── {project_name}/             # Project package (app-specific modules only)
│   ├── __init__.py
│   ├── db.py                   # App-specific DB operations
│   ├── utils.py                # App-specific utilities
│   └── error_utils.py          # App-specific error handling
├── sql/
│   ├── postgres/               # SQL files for Postgres
│   │   ├── select_users.sql
│   │   ├── insert_records.sql
│   │   └── update_status.sql
│   └── sqlserver/              # SQL files for SQL Server (if used)
│       └── procedures/
├── tests/
│   ├── conftest.py             # Shared pytest fixtures
│   └── {project_name}/
│       ├── test_db.py
│       ├── test_utils.py
│       └── test_error_utils.py
├── .env                        # Local secrets (NEVER commit)
├── .env.example                # Template for .env
├── .gitignore                  # Must exclude .venv/, .env, __pycache__, *.pyc
├── .venv/                      # Virtual environment
├── requirements.txt            # All dependencies pinned to versions
├── README.md                   # Purpose, setup, run instructions
└── LICENSE
```

### Key Rules

- `main.py` contains **orchestration only** — no business logic
- All reusable/generic logic goes in a shared library (e.g., `rey_lib`)
- App-specific logic stays in `{project_name}/`
- If logic doesn't make sense in another project, it's app-specific
- Each function lives in the **most appropriate module**, not for convenience
- SQL files live in `sql/{database_type}/` — none inline in Python
- SQL files named with pattern: `{verb}_{subject}.sql` (e.g., `select_users.sql`, `update_status.sql`)
- Never duplicate logic that exists in shared libraries — always import and use it

---

## Configuration Management

### Config File Format

- All config in **YAML format**
- Main config naming: `config.dev.yaml`, `config.prod.yaml`
- Additional configs in named subdirectories: `config/db/`, `config/data_feeds/`, `config/app/`
- Environment separation at minimum: `dev` and `prod`

### Config Loading

```python
# Load config once at startup
import sys
from pathlib import Path
from rey_lib.config.config_utils import build_ctx

_PROJECT_ROOT = Path(__file__).parent
ctx = build_ctx(env='dev', project_root=_PROJECT_ROOT)

# Access values from ctx throughout application
chunk_size = ctx.get('data.chunk_size')
db_host = ctx.get('database.host')
```

### Config File Structure

```yaml
# config/config.dev.yaml
---
database:
  host: localhost
  port: 5432
  name: myapp_dev
  
data:
  chunk_size: 5000
  
logging:
  level: DEBUG
  
secrets:
  db_password:
    env: DB_PASSWORD
  api_key:
    env: API_KEY
```

### Secrets

- Never hard-code secrets in config files
- Use `.env` file for local secrets: `pip install python-dotenv`
- Secrets in YAML declared via `env:` block
- Library (e.g., `rey_lib`) resolves them from environment automatically
- Never call custom injection unless explicitly required
- Never log credentials, tokens, or PII

```yaml
# In config.yaml
database:
  password:
    env: DB_PASSWORD  # Resolved from environment

secrets:
  api_key:
    env: API_KEY      # Resolved from environment
```

```bash
# In .env (never committed)
DB_PASSWORD=actual_password_here
API_KEY=sk-xxxxxxxxxxxx
```

---

## Module and Function Placement

### Dependency Direction

```
main.py → {project_name}/* → shared_lib → stdlib
```

Only import in this direction. Never:
- Import `main.py` from anywhere
- Create circular imports between modules
- Import app-specific logic into shared library

### Function Placement Rules

**In `{project_name}/` (app-specific):**
- Business logic specific to this project
- Data transformations unique to this application
- Orchestration of domain operations
- Error handling specific to this app

**In shared library (e.g., `rey_lib`):**
- Generic SQL utilities
- Generic database connection pooling
- Logging infrastructure
- Configuration loading
- Generic data formatting utilities

**Never:**
- Put app-specific logic in shared library
- Put multiple unrelated functions in one module
- Use a module just because it's convenient

---

## Entry Point and Runtime

### main.py Template

```python
"""Application entry point and orchestration."""
import argparse
import logging
from pathlib import Path
from rey_lib.config.config_utils import build_ctx
from {project_name} import process_records

_PROJECT_ROOT = Path(__file__).parent
logger = logging.getLogger(__name__)

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Process records')
    parser.add_argument(
        '--env',
        choices=['dev', 'prod'],
        required=True,
        help='Runtime environment (dev or prod)'
    )
    parser.add_argument(
        '--batch-id',
        type=int,
        required=True,
        help='Batch ID to process'
    )
    
    args = parser.parse_args()
    
    try:
        # Load config once
        ctx = build_ctx(env=args.env, project_root=_PROJECT_ROOT)
        
        # Orchestrate work
        result = process_records(ctx, batch_id=args.batch_id)
        
        logger.info(f"Processed {result} records")
        return 0
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    exit(main())
```

### CLI Arguments

- Use `argparse` only — never parse `sys.argv` directly
- Environment (dev/prod/etc.) **always** passed as CLI argument
- Never infer or hard-code environment
- Always return explicit exit codes:
  - `0` for success
  - Non-zero for any failure

---

## Module Public API

Declare module-level API with `__all__`:

```python
# {project_name}/db.py
"""Database operations."""

__all__ = ['fetch_users', 'update_user_status']

def fetch_users(ctx: Context) -> list[dict]:
    """Fetch all active users."""
    # implementation
    pass

def update_user_status(ctx: Context, user_id: int, status: str) -> bool:
    """Update user status."""
    # implementation
    pass

def _internal_helper(data: dict) -> dict:
    """Internal helper — not in public API."""
    # implementation
    pass
```

---

## Security

### General Security

- Secrets and credentials never in config files or source code
- Use environment variables or `.env` file
- `ctx` holds resolved values, never raw secrets
- Never log credentials, tokens, or PII

### SQL Security

- All SQL must use **parameterized queries** — string-formatted SQL forbidden
- This is enforced in all database utility modules

### Input Validation

- Validate at entry boundaries (not against adversarial attacks, against bad data)
- Don't expose stack traces in user-facing output
- Log errors internally but return generic messages to users

### .gitignore

Must exclude at minimum:

```
.venv/
.env
*.pyc
__pycache__/
*.db
*.log
```

---

## Version Control & Code Changes

### Change Control

When modifying existing code:

- Do **not** rewrite the entire file
- Show **only** the modified sections
- Include surrounding context to make changes unambiguous
- Preserve all surrounding formatting, comments, docstrings
- Do not reformat, renumber, or reorder outside changed section
- Explain changes only if explicitly requested

Example:
```python
# In module: {project_name}/db.py
# Only show this section:

def fetch_active_users(ctx: Context) -> list[dict]:
    """Fetch all active users from database."""
    with get_connection(ctx) as conn:
        # CHANGED: Added created_date filter
        query = """
        SELECT user_id, user_name, created_date
        FROM users
        WHERE status = 'active'
          AND created_date >= :cutoff_date
        """
        return conn.execute(
            query,
            {'cutoff_date': ctx.get('user.min_created_date')}
        ).fetchall()
```

---

## Dependencies

### requirements.txt

All dependencies **pinned to specific versions**:

```
# CORRECT
requests==2.31.0
sqlalchemy==2.0.23
python-dotenv==1.0.0
pytest==7.4.2

# WRONG
requests
sqlalchemy>=2.0
```

### Linting & Formatting

All projects must include:
- `ruff` or `flake8` for linting
- `black` for auto-formatting

Both pinned in `requirements.txt`.

Code must pass linting and formatting checks before considered complete.

---

## Testing

- Use `pytest` exclusively — never `unittest`
- Shared fixtures in `tests/conftest.py`
- Mock DB and external calls — never connect to real systems in tests
- Test structure mirrors source: `tests/{project_name}/test_module.py`
- Test file name must match target: `test_db.py` tests `db.py`
- Coverage: happy path, edge cases, error paths
- Pin `pytest` in `requirements.txt`

