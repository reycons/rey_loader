"""rey_loader — database module.

All database interaction goes through rey_lib.db.db_adapter.DBAdapter, which
dispatches to the appropriate backend (SQL Server, DuckDB, etc.) based on
each connection config's `provider` field. No application-specific database
code lives in rey_loader.
"""
