---
name: python-standards
description: Detailed Python engineering standards and conventions
---

# Python Engineering Standards

## Naming Conventions

- Functions and variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private functions/variables: prefix with `_name`
- Module-level public API: declare with `__all__`

---

## Code Quality Rules

### Type Hints & Docstrings

- Type hints on **all** function signatures, including explicit return types (`-> str`, `-> None`, `-> list[str]`)
- All functions, classes, and modules must have docstrings
- Comments **and** docstrings are both required — they serve different purposes
- Docstrings explain *what* and *why*; comments explain *how*

Example:
```python
def process_records(ctx: Context, records: list[dict]) -> list[str]:
    """
    Process records and return IDs of successful items.
    
    Args:
        ctx: Runtime context containing config and logging.
        records: List of dictionaries containing record data.
    
    Returns:
        List of successfully processed record IDs.
    """
    # Filter out records missing required keys
    valid = [r for r in records if 'id' in r]
    
    # Process each valid record
    return [_process_record(ctx, r) for r in valid]
```

### Code Style

- Clarity over cleverness
- No unnecessary abstractions
- PEP 8 compliance mandatory
- Max line length: 100 characters
- Code must be readable by another engineer in 6 months
- Functions do one thing only — if scrolling required, split into helpers
- Large operations decomposed into focused helper functions

### Imports

Order:
1. Standard library
2. Third-party packages
3. Local imports

Blank line between each group. No wildcard imports (`from x import *`).

```python
# Standard library
import json
import logging
from pathlib import Path

# Third-party
import requests
from sqlalchemy import create_engine

# Local
from myproject.db import get_connection
from myproject.utils import format_date
```

### Forbidden Patterns

- ❌ Mutable default arguments: `def f(x=[])` or `def f(x={})`
  - Use `None` and assign inside: `def f(x=None): x = x or []`
- ❌ `global` keyword — pass values explicitly or use `ctx`
- ❌ Broad `except Exception` outside `error_utils.py`
- ❌ Circular imports — move shared logic to third module
- ❌ No commented-out code in production files
- ❌ `print()` statements — use logging instead

---

## Error Handling & Logging

### Exception Chaining

Always use `raise NewException("message") from original` when re-raising:

```python
try:
    result = risky_operation()
except ValueError as e:
    # CORRECT: preserves original traceback
    raise ProcessingError(f"Could not process: {e}") from e
    
    # WRONG: loses original traceback
    # raise ProcessingError(f"Could not process: {e}")
```

### Logging

- Use logging instead of print: `ctx.log("message")`
- Never log credentials, tokens, or PII
- Log at meaningful intervals for long operations
- Respect `ctx.log_level` to control verbosity

```python
import logging

logger = logging.getLogger(__name__)

def process_large_dataset(ctx: Context, data: list) -> None:
    """Process dataset with progress logging."""
    ctx.log_enter(f"Processing {len(data)} items")
    
    for i, item in enumerate(data):
        _process_item(ctx, item)
        
        # Log progress at intervals
        if (i + 1) % 1000 == 0:
            ctx.log(f"Processed {i + 1} items")
    
    ctx.log_exit("Processing complete")
```

---

## Resource Management

Use context managers for any resource requiring cleanup:

```python
# CORRECT: Context manager ensures cleanup
with open(filepath) as f:
    content = f.read()

# CORRECT: DB connection context manager
with get_connection(ctx) as conn:
    result = conn.execute(query)

# WRONG: Manual open/close
f = open(filepath)
content = f.read()
f.close()  # Not guaranteed to run if exception occurs
```

---

## Data Handling

- Never load entire large result sets into memory
- Use server-side cursors or chunked fetching for >1000 rows
- Chunk size must be a config value in `ctx` — never hard-coded
- When processing rows, iterate — don't accumulate into list unless full dataset required
- Prefer native Python structures over pandas unless clearly justified
- If pandas used, pin in `requirements.txt` and confine to one module

```python
def process_large_result(ctx: Context, query: str) -> None:
    """Process query results in chunks to avoid memory issues."""
    chunk_size = ctx.get('data.chunk_size', 5000)
    
    with get_connection(ctx) as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        
        # Fetch and process in chunks
        while True:
            rows = cursor.fetchmany(chunk_size)
            if not rows:
                break
            
            for row in rows:
                _process_row(ctx, row)
```

---

## File & Path Operations

Always use `pathlib.Path`:

```python
from pathlib import Path

# CORRECT: Use pathlib
config_dir = Path.home() / '.config' / 'myapp'
config_file = config_dir / 'settings.yaml'

# WRONG: String concatenation
# config_dir = os.path.expanduser('~') + '/.config/myapp'
# config_file = config_dir + '/settings.yaml'

# Creating parent directories
config_file.parent.mkdir(parents=True, exist_ok=True)

# Reading files
with open(config_file) as f:
    content = f.read()
```

---

## Dependencies

- Maintain `requirements.txt` with **pinned versions**
  - ❌ Wrong: `requests`
  - ✅ Correct: `requests==2.31.0`
- All projects must include `ruff` or `flake8` (linting) and `black` (formatting)
- All dependencies pinned in `requirements.txt`
- Code must pass linting and formatting checks before completion

---

## Testing

- Use `pytest` exclusively — never `unittest`
- All functions in `{project_name}/` must have unit tests
- Shared fixtures in `tests/conftest.py` — never duplicate
- Mock DB and external calls — tests never connect to real systems
- Test structure mirrors source: `tests/{project_name}/test_db.py` for `{project_name}/db.py`
- Test coverage: happy path, edge cases, and error paths
- Pin `pytest` in `requirements.txt`

Example test structure:
```python
# tests/conftest.py
import pytest
from myproject.db import DatabaseConnection

@pytest.fixture
def mock_ctx(mocker):
    """Shared fixture for context object."""
    ctx = mocker.MagicMock()
    ctx.get = mocker.MagicMock(side_effect=lambda k, d=None: d)
    return ctx

# tests/myproject/test_db.py
from myproject.db import fetch_users

def test_fetch_users_success(mock_ctx, mocker):
    """Test happy path."""
    mocker.patch('myproject.db.get_connection')
    result = fetch_users(mock_ctx)
    assert len(result) > 0

def test_fetch_users_empty(mock_ctx, mocker):
    """Test edge case."""
    mocker.patch('myproject.db.get_connection', return_value=[])
    result = fetch_users(mock_ctx)
    assert result == []

def test_fetch_users_connection_error(mock_ctx, mocker):
    """Test error path."""
    mocker.patch('myproject.db.get_connection', side_effect=ConnectionError)
    with pytest.raises(ConnectionError):
        fetch_users(mock_ctx)
```

---

## Virtual Environments

- All projects must use `venv` — never install globally
- Create: `python -m venv .venv`
- Activate: `source .venv/bin/activate` (Linux/Mac) or `.venv\Scripts\activate` (Windows)
- Pin Python version in `README.md`

