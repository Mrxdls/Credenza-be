"""
Cloudflare D1 Serverless SQL Database Service.

Provides remote query execution, batch DDL execution, database status inspection,
and schema synchronization for Cloudflare D1 via the Cloudflare REST API v4.
Supports dynamic credentials from SystemConfiguration and environment variables.
"""
from dataclasses import dataclass
import io
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"


@dataclass(frozen=True)
class D1Config:
    """Immutable value object holding Cloudflare D1 connection parameters."""
    account_id: str = ""
    database_id: str = ""
    api_token: str = ""

    @classmethod
    def from_settings(cls) -> "D1Config":
        """Loads configuration parameters from Django environment settings."""
        return cls(
            account_id=getattr(settings, 'CLOUDFLARE_ACCOUNT_ID', ''),
            database_id=getattr(settings, 'CLOUDFLARE_D1_DATABASE_ID', ''),
            api_token=getattr(settings, 'CLOUDFLARE_D1_API_TOKEN', ''),
        )

    @classmethod
    def from_dict(cls, data: dict) -> "D1Config":
        """Loads configuration parameters from a plain dictionary."""
        return cls(
            account_id=data.get("account_id", ""),
            database_id=data.get("database_id", ""),
            api_token=data.get("api_token", ""),
        )

    def to_dict(self) -> dict:
        """Converts configuration to a dictionary for backward compatibility."""
        return {
            "account_id": self.account_id,
            "database_id": self.database_id,
            "api_token": self.api_token,
        }

    @property
    def is_valid(self) -> bool:
        """Checks if all required Cloudflare D1 credentials are present."""
        return bool(self.account_id and self.database_id and self.api_token)


class CloudflareD1Service:
    """
    Object-oriented Cloudflare D1 database service.

    Encapsulates REST authentication headers, query execution, batch DDL executions,
    schema extraction, and connectivity diagnostics.
    """

    def __init__(self, config: Optional[Union[D1Config, dict]] = None):
        if config is None:
            self.config = D1Config.from_settings()
        elif isinstance(config, dict):
            self.config = D1Config.from_dict(config)
        elif isinstance(config, D1Config):
            self.config = config
        else:
            raise TypeError(f"Invalid config type: {type(config)}")

    @property
    def is_configured(self) -> bool:
        """Returns True if required D1 credentials are present."""
        return self.config.is_valid

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.api_token}",
            "Content-Type": "application/json",
            "User-Agent": "Poornima-Achievements-D1/1.0",
        }

    def _ensure_configured(self):
        if not self.is_configured:
            raise ValueError(
                "Cloudflare D1 credentials missing. Please configure CLOUDFLARE_ACCOUNT_ID, "
                "CLOUDFLARE_D1_DATABASE_ID, and CLOUDFLARE_D1_API_TOKEN in your environment (.env)."
            )

    def execute_query(
        self,
        sql: str,
        params: Optional[List[Any]] = None,
        timeout: int = 30,
    ) -> dict:
        """
        Executes a SQL query against the remote Cloudflare D1 database via Cloudflare REST API.

        Endpoint: POST https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query
        """
        self._ensure_configured()
        url = f"{CLOUDFLARE_API_BASE}/accounts/{self.config.account_id}/d1/database/{self.config.database_id}/query"
        payload = {
            "sql": sql,
            "params": params or [],
        }

        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=timeout,
            )
            data = response.json()
            if not response.ok or not data.get("success"):
                errors = data.get("errors", [{"message": response.text}])
                return {
                    "success": False,
                    "error": errors[0].get("message", "Unknown D1 API error") if errors else response.text,
                    "errors": errors,
                    "status_code": response.status_code,
                }

            # D1 wraps results in an array of result sets (one per query statement)
            result_sets = data.get("result", [])
            primary_result = result_sets[0] if result_sets else {}

            return {
                "success": True,
                "results": primary_result.get("results", []),
                "meta": primary_result.get("meta", {}),
                "all_results": result_sets,
            }
        except requests.RequestException as e:
            logger.error(f"Cloudflare D1 query request failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "errors": [{"message": str(e)}],
            }

    def execute_read(
        self,
        sql: str,
        params: Optional[List[Any]] = None,
        timeout: int = 30,
    ) -> dict:
        """
        Executes a SQL read query (e.g. SELECT, PRAGMA) on Cloudflare D1 via REST API.
        Returns a dictionary with query status, row count, and parsed result rows.
        """
        res = self.execute_query(sql, params=params, timeout=timeout)
        if not res.get("success"):
            return {
                "success": False,
                "rows": [],
                "results": [],
                "count": 0,
                "error": res.get("error", "Unknown read error"),
                "errors": res.get("errors", []),
            }

        rows = res.get("results", [])
        return {
            "success": True,
            "rows": rows,
            "results": rows,
            "count": len(rows),
            "meta": res.get("meta", {}),
        }

    def execute_write(
        self,
        sql: str,
        params: Optional[List[Any]] = None,
        timeout: int = 30,
    ) -> dict:
        """
        Executes a SQL mutation / write query (e.g. INSERT, UPDATE, DELETE, DDL) on Cloudflare D1.
        Returns a dictionary with execution status, changes count, and last inserted row ID.
        """
        res = self.execute_query(sql, params=params, timeout=timeout)
        if not res.get("success"):
            return {
                "success": False,
                "changes": 0,
                "rows_written": 0,
                "last_row_id": None,
                "error": res.get("error", "Unknown write error"),
                "errors": res.get("errors", []),
            }

        meta = res.get("meta", {})
        return {
            "success": True,
            "changes": meta.get("changes", 0),
            "rows_written": meta.get("rows_written", 0),
            "last_row_id": meta.get("last_row_id"),
            "meta": meta,
        }

    @staticmethod
    def split_sql_script(sql_script: str) -> List[str]:
        """
        Splits a multi-statement SQL script into individual executable statements.
        Handles single and multiline comments, single/double quoted strings (with escaped
        quotes and semicolons), and filters out transaction statements (BEGIN/COMMIT).
        """
        import sqlite3
        statements = []
        buffer = []
        in_quote = None
        in_line_comment = False
        in_block_comment = False
        i = 0
        n = len(sql_script)

        while i < n:
            c = sql_script[i]
            next_c = sql_script[i + 1] if i + 1 < n else ""

            if in_line_comment:
                if c == "\n":
                    in_line_comment = False
                    buffer.append(c)
                i += 1
                continue

            if in_block_comment:
                if c == "*" and next_c == "/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            if in_quote:
                buffer.append(c)
                if c == in_quote:
                    if next_c == in_quote:
                        buffer.append(next_c)
                        i += 2
                        continue
                    in_quote = None
                i += 1
                continue

            if c == "-" and next_c == "-":
                in_line_comment = True
                i += 2
                continue

            if c == "/" and next_c == "*":
                in_block_comment = True
                i += 2
                continue

            if c in ("'", '"'):
                in_quote = c
                buffer.append(c)
                i += 1
                continue

            buffer.append(c)
            if c == ";":
                candidate = "".join(buffer).strip()
                if sqlite3.complete_statement(candidate):
                    clean = candidate.rstrip(";").strip()
                    upper = clean.upper()
                    if upper and upper not in ("BEGIN", "BEGIN TRANSACTION", "COMMIT", "END", "END TRANSACTION"):
                        statements.append(clean + ";")
                    buffer = []
            i += 1

        remainder = "".join(buffer).strip()
        if remainder:
            clean = remainder.rstrip(";").strip()
            upper = clean.upper()
            if upper and upper not in ("BEGIN", "BEGIN TRANSACTION", "COMMIT", "END", "END TRANSACTION"):
                statements.append(clean + ";")

        return statements

    def execute_batch(
        self,
        statements: List[str],
        chunk_size: int = 25,
        timeout: int = 60,
    ) -> dict:
        """
        Executes multiple SQL statements sequentially or in batches on Cloudflare D1 via REST API.
        Chunks statements to prevent payload overflow and aggregates changes and timing metrics.
        """
        self._ensure_configured()
        clean_stmts = [s.strip().rstrip(";") + ";" for s in statements if s.strip()]
        if not clean_stmts:
            return {
                "success": True,
                "total_statements": 0,
                "executed_statements": 0,
                "batches_executed": 0,
                "changes": 0,
                "rows_written": 0,
                "rows_read": 0,
                "duration": 0.0,
                "all_results": [],
            }

        all_results = []
        total_changes = 0
        total_rows_written = 0
        total_rows_read = 0
        total_duration = 0.0
        errors = []

        batches = [clean_stmts[i : i + chunk_size] for i in range(0, len(clean_stmts), chunk_size)]

        for batch in batches:
            combined_sql = "\n".join(batch)
            res = self.execute_query(combined_sql, timeout=timeout)
            if not res.get("success"):
                err_msg = res.get("error", "Unknown error in batch execution")
                errors.append(err_msg)
                return {
                    "success": False,
                    "total_statements": len(clean_stmts),
                    "executed_statements": len(all_results),
                    "batches_executed": len(all_results) // max(1, chunk_size),
                    "error": err_msg,
                    "errors": errors,
                    "all_results": all_results,
                }

            chunk_results = res.get("all_results", [])
            all_results.extend(chunk_results)
            for r in chunk_results:
                meta = r.get("meta", {})
                total_changes += meta.get("changes", 0)
                total_rows_written += meta.get("rows_written", 0)
                total_rows_read += meta.get("rows_read", 0)
                total_duration += meta.get("duration", 0.0)

        return {
            "success": True,
            "total_statements": len(clean_stmts),
            "executed_statements": len(clean_stmts),
            "batches_executed": len(batches),
            "changes": total_changes,
            "rows_written": total_rows_written,
            "rows_read": total_rows_read,
            "duration": round(total_duration, 4),
            "all_results": all_results,
        }

    def execute_script(
        self,
        sql_script: str,
        chunk_size: int = 25,
        timeout: int = 60,
    ) -> dict:
        """
        Parses and executes a multi-statement SQL script against Cloudflare D1 via REST API.
        """
        statements = self.split_sql_script(sql_script)
        if not statements:
            return {
                "success": True,
                "total_statements": 0,
                "executed_statements": 0,
                "batches_executed": 0,
                "changes": 0,
            }
        return self.execute_batch(statements, chunk_size=chunk_size, timeout=timeout)

    def apply_schema(
        self,
        schema_sql: Optional[str] = None,
        schema_file: Optional[str] = None,
        chunk_size: int = 25,
        timeout: int = 120,
    ) -> dict:
        """
        Applies a database schema directly to Cloudflare D1 via Cloudflare REST API without Wrangler.
        """
        if schema_file:
            if not os.path.exists(schema_file):
                return {"success": False, "error": f"Schema file not found: {schema_file}"}
            with open(schema_file, "r", encoding="utf-8") as f:
                content = f.read()
        elif schema_sql:
            content = schema_sql
        else:
            content = self.export_django_schema()

        return self.execute_script(content, chunk_size=chunk_size, timeout=timeout)

    def list_tables(self) -> List[str]:
        """Returns a sorted list of user-created table names in Cloudflare D1."""
        res = self.execute_read(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        )
        if res.get("success"):
            return [row["name"] for row in res.get("rows", []) if "name" in row]
        return []

    def get_table_counts(self) -> Dict[str, int]:
        """Returns a mapping of {table_name: row_count} for all tables in D1."""
        tables = self.list_tables()
        counts = {}
        for table in tables:
            safe_name = table.replace('"', '""')
            res = self.execute_read(f'SELECT count(*) AS cnt FROM "{safe_name}";')
            if res.get("success") and res.get("rows"):
                counts[table] = res["rows"][0].get("cnt", 0)
            else:
                counts[table] = 0
        return counts

    def get_database_info(self, timeout: int = 15) -> dict:
        """Fetches database metadata from Cloudflare D1 API."""
        if not self.is_configured:
            return {"success": False, "error": "Cloudflare D1 credentials not configured"}

        url = f"{CLOUDFLARE_API_BASE}/accounts/{self.config.account_id}/d1/database/{self.config.database_id}"
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=timeout)
            data = response.json()
            if response.ok and data.get("success"):
                return {"success": True, "database": data.get("result", {})}
            return {"success": False, "error": data.get("errors", [{"message": response.text}])[0].get("message")}
        except requests.RequestException as e:
            return {"success": False, "error": str(e)}

    def test_connection(self) -> Tuple[bool, str]:
        """Verifies Cloudflare D1 connectivity by executing a lightweight probe query."""
        if not self.is_configured:
            return False, "Missing Cloudflare Account ID, D1 Database ID, or API Token."

        result = execute_d1_query("SELECT 1 AS probe, datetime('now') AS d1_now;", config=self.config.to_dict())
        if result.get("success"):
            rows = result.get("results", [])
            now_val = rows[0].get("d1_now", "") if rows else ""
            return True, f"Successfully connected to Cloudflare D1. Remote timestamp: {now_val}"
        return False, f"Cloudflare D1 query failed: {result.get('error', 'Unknown error')}"

    @staticmethod
    def export_django_schema(sqlite_path: Optional[str] = None) -> str:
        """
        Generates a clean, SQLite/D1 compatible DDL schema string for Cloudflare D1.
        Extracts pure SQLite schema from SQLite master, strips any transaction wrappers
        (avoiding Cloudflare D1's transaction error), and ensures IF NOT EXISTS idempotency.
        """
        import sqlite3
        db_file = sqlite_path or str(settings.BASE_DIR / 'db.sqlite3')

        # If db.sqlite3 doesn't exist, create it and run migrations
        if not os.path.exists(db_file):
            from django.core.management import call_command
            call_command('migrate', verbosity=0)

        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name ASC;")
        raw_statements = [row[0].strip() for row in cursor.fetchall()]
        conn.close()

        buffer = io.StringIO()
        buffer.write("-- ========================================================\n")
        buffer.write("-- Poornima University Faculty Achievements Portal\n")
        buffer.write("-- Cloudflare D1 SQLite Compatible Database Schema\n")
        buffer.write("-- ========================================================\n\n")
        buffer.write("PRAGMA foreign_keys = ON;\n\n")

        for stmt in raw_statements:
            clean = stmt.rstrip(';') + ';'
            # Cloudflare D1 compatibility: Ensure IF NOT EXISTS for tables and indexes
            if clean.startswith("CREATE TABLE ") and "CREATE TABLE IF NOT EXISTS" not in clean:
                clean = clean.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
            elif clean.startswith("CREATE UNIQUE INDEX ") and "IF NOT EXISTS" not in clean:
                clean = clean.replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1)
            elif clean.startswith("CREATE INDEX ") and "IF NOT EXISTS" not in clean:
                clean = clean.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)
            buffer.write(clean + "\n\n")

        return buffer.getvalue()


# ── Backward-Compatible Functional API ────────────────────────────────────────

def get_d1_config() -> dict:
    """Retrieves Cloudflare D1 configuration as a dictionary."""
    return D1Config.from_settings().to_dict()


def execute_d1_query(
    sql: str,
    params: Optional[List[Any]] = None,
    config: Optional[dict] = None,
    timeout: int = 30,
) -> dict:
    """Executes a SQL query against the remote Cloudflare D1 database via REST API."""
    service = CloudflareD1Service(config=config)
    return service.execute_query(sql, params=params, timeout=timeout)


def execute_d1_read(
    sql: str,
    params: Optional[List[Any]] = None,
    config: Optional[dict] = None,
    timeout: int = 30,
) -> dict:
    """Executes a SQL read query (SELECT) against Cloudflare D1 via REST API."""
    service = CloudflareD1Service(config=config)
    return service.execute_read(sql, params=params, timeout=timeout)


def execute_d1_write(
    sql: str,
    params: Optional[List[Any]] = None,
    config: Optional[dict] = None,
    timeout: int = 30,
) -> dict:
    """Executes a SQL mutation query (INSERT, UPDATE, DELETE) against Cloudflare D1 via REST API."""
    service = CloudflareD1Service(config=config)
    return service.execute_write(sql, params=params, timeout=timeout)


def execute_d1_batch(
    statements: List[str],
    config: Optional[dict] = None,
    chunk_size: int = 25,
    timeout: int = 60,
) -> dict:
    """Executes multiple SQL statements in batches against Cloudflare D1 via REST API."""
    service = CloudflareD1Service(config=config)
    return service.execute_batch(statements, chunk_size=chunk_size, timeout=timeout)


def execute_d1_script(
    sql_script: str,
    config: Optional[dict] = None,
    chunk_size: int = 25,
    timeout: int = 60,
) -> dict:
    """Parses and executes a multi-statement SQL script against Cloudflare D1 via REST API."""
    service = CloudflareD1Service(config=config)
    return service.execute_script(sql_script, chunk_size=chunk_size, timeout=timeout)


def apply_d1_schema(
    schema_sql: Optional[str] = None,
    schema_file: Optional[str] = None,
    config: Optional[dict] = None,
    chunk_size: int = 25,
    timeout: int = 120,
) -> dict:
    """Applies database schema directly to Cloudflare D1 via REST API without Wrangler."""
    service = CloudflareD1Service(config=config)
    return service.apply_schema(schema_sql=schema_sql, schema_file=schema_file, chunk_size=chunk_size, timeout=timeout)


def list_d1_tables(config: Optional[dict] = None) -> List[str]:
    """Lists non-internal table names in Cloudflare D1."""
    service = CloudflareD1Service(config=config)
    return service.list_tables()


def get_d1_database_info(config: Optional[dict] = None) -> dict:
    """Fetches database metadata from Cloudflare D1 API."""
    service = CloudflareD1Service(config=config)
    return service.get_database_info()


def test_d1_connection(config: Optional[dict] = None) -> Tuple[bool, str]:
    """Verifies Cloudflare D1 connectivity by executing a lightweight probe query."""
    service = CloudflareD1Service(config=config)
    return service.test_connection()


def export_django_schema_for_d1(sqlite_path: Optional[str] = None) -> str:
    """Generates a clean, SQLite/D1 compatible DDL schema string for Cloudflare D1."""
    return CloudflareD1Service.export_django_schema(sqlite_path=sqlite_path)
