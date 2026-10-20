"""Data sources: local exports and the ServiceNow Table API."""

from cmdb_health.sources.local import DataSourceError, load_local

__all__ = ["DataSourceError", "load_local"]
